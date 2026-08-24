"""Shared helpers for the genetic-tractability discovery pipeline.

Lightweight, dependency-light (requests + stdlib only) utilities for
querying Europe PMC and NCBI E-utilities, on-disk JSON caching, CSV I/O,
and paper/observation ID generation. Deliberately standalone rather than
wired into fair_ocean_agent's ORM/task-queue -- that pipeline's Study/
Entity/FAIRe model doesn't fit this project's paper -> observation shape,
and the spec calls for flat CSV outputs.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "genetic_tractability"
CACHE_DIR = REPO_ROOT / "data" / "cache"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CONTACT_EMAIL = os.environ.get("GENETIC_TRACTABILITY_CONTACT_EMAIL", "research@example.org")
USER_AGENT = f"genetic-tractability-discovery/0.1 (mailto:{CONTACT_EMAIL})"

EPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
NCBI_EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})

_last_request_time: Dict[str, float] = {}
_MIN_INTERVAL = 0.2  # ~5 req/s, still polite for unauthenticated public APIs but faster for a much larger discovery scope


def _throttle(host: str) -> None:
    now = time.time()
    last = _last_request_time.get(host, 0.0)
    wait = _MIN_INTERVAL - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_request_time[host] = time.time()


def _cache_path(url: str) -> Path:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{key}.json"


def cached_get_json(url: str, host_key: str, retries: int = 3) -> Optional[dict]:
    cache_path = _cache_path(url)
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except Exception:
            pass
    for attempt in range(retries):
        _throttle(host_key)
        try:
            resp = _session.get(url, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                cache_path.write_text(json.dumps(data))
                return data
            if resp.status_code == 404:
                return None
            time.sleep(1.5 * (attempt + 1))
        except requests.RequestException:
            time.sleep(1.5 * (attempt + 1))
    return None


def cached_get_text(url: str, host_key: str, retries: int = 3) -> Optional[str]:
    cache_key = _cache_path(url).with_suffix(".txt")
    if cache_key.exists():
        return cache_key.read_text()
    for attempt in range(retries):
        _throttle(host_key)
        try:
            resp = _session.get(url, timeout=30)
            if resp.status_code == 200:
                cache_key.write_text(resp.text)
                return resp.text
            if resp.status_code == 404:
                return None
            time.sleep(1.5 * (attempt + 1))
        except requests.RequestException:
            time.sleep(1.5 * (attempt + 1))
    return None


# ---------------------------------------------------------------------------
# Europe PMC
# ---------------------------------------------------------------------------

def epmc_search(query: str, max_results: int = 100, result_type: str = "core", sort: str = "") -> List[dict]:
    """Search Europe PMC, following cursorMark pagination up to max_results.

    sort="" uses Europe PMC's default relevance ranking; sort="CITED desc"
    (etc.) surfaces older, highly-cited reviews that pure text relevance
    can bury under recently-published noise.
    """
    results: List[dict] = []
    cursor = "*"
    page_size = min(100, max_results)
    while len(results) < max_results:
        params = {
            "query": query,
            "format": "json",
            "resultType": result_type,
            "pageSize": page_size,
            "cursorMark": cursor,
        }
        if sort:
            params["sort"] = sort
        url = f"{EPMC_BASE}/search?{urllib.parse.urlencode(params)}"
        data = cached_get_json(url, "epmc")
        if not data:
            break
        batch = data.get("resultList", {}).get("result", [])
        results.extend(batch)
        next_cursor = data.get("nextCursorMark")
        if not next_cursor or next_cursor == cursor or not batch:
            break
        cursor = next_cursor
    return results[:max_results]


def epmc_references(source: str, ext_id: str, max_results: int = 600) -> List[dict]:
    """Fetch the structured reference list Europe PMC has for a given article."""
    refs: List[dict] = []
    page = 1
    while True:
        url = f"{EPMC_BASE}/{source}/{ext_id}/references?format=json&page={page}&pageSize=100"
        data = cached_get_json(url, "epmc")
        if not data:
            break
        batch = data.get("referenceList", {}).get("reference", [])
        refs.extend(batch)
        if len(batch) < 100 or len(refs) >= max_results:
            break
        page += 1
    return refs[:max_results]


def epmc_fulltext_xml(pmcid: str) -> Optional[str]:
    url = f"{EPMC_BASE}/{pmcid}/fullTextXML"
    return cached_get_text(url, "epmc")


def epmc_lookup_record(doi: str = "", pmid: str = "", title: str = "") -> Optional[dict]:
    """Fetch one full Europe PMC core record (title/abstract/OA status/pmcid/...)."""
    if doi:
        query = f'DOI:"{normalize_doi(doi)}"'
    elif pmid:
        query = f"EXT_ID:{pmid} AND SRC:MED"
    elif title:
        query = f'TITLE:"{title}"'
    else:
        return None
    url = f"{EPMC_BASE}/search?{urllib.parse.urlencode({'query': query, 'format': 'json', 'resultType': 'core', 'pageSize': 1})}"
    data = cached_get_json(url, "epmc")
    if not data:
        return None
    results = data.get("resultList", {}).get("result", [])
    if not results:
        return None
    return parse_epmc_record(results[0])


# ---------------------------------------------------------------------------
# NCBI E-utilities (genome assembly lookup)
# ---------------------------------------------------------------------------

def ncbi_esearch(db: str, term: str, retmax: int = 20) -> List[str]:
    params = {
        "db": db,
        "term": term,
        "retmode": "json",
        "retmax": retmax,
        "email": CONTACT_EMAIL,
        "tool": "genetic-tractability-discovery",
    }
    url = f"{NCBI_EUTILS_BASE}/esearch.fcgi?{urllib.parse.urlencode(params)}"
    data = cached_get_json(url, "ncbi")
    if not data:
        return []
    return data.get("esearchresult", {}).get("idlist", [])


def ncbi_esummary(db: str, ids: List[str]) -> dict:
    if not ids:
        return {}
    params = {
        "db": db,
        "id": ",".join(ids),
        "retmode": "json",
        "email": CONTACT_EMAIL,
        "tool": "genetic-tractability-discovery",
    }
    url = f"{NCBI_EUTILS_BASE}/esummary.fcgi?{urllib.parse.urlencode(params)}"
    data = cached_get_json(url, "ncbi")
    if not data:
        return {}
    return data.get("result", {})


# ---------------------------------------------------------------------------
# Identifiers / normalization
# ---------------------------------------------------------------------------

def normalize_title(title: Optional[str]) -> str:
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def normalize_doi(doi: Optional[str]) -> str:
    if not doi:
        return ""
    return doi.strip().lower().removeprefix("https://doi.org/").removeprefix("doi:")


def make_paper_id(doi: Optional[str], pmid: Optional[str], title: Optional[str]) -> str:
    if doi:
        basis = f"doi:{normalize_doi(doi)}"
    elif pmid:
        basis = f"pmid:{pmid}"
    else:
        basis = f"title:{normalize_title(title)}"
    h = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
    return f"P{h}"


def make_observation_id(paper_id: str, index: int) -> str:
    return f"{paper_id}-OBS{index:02d}"


# ---------------------------------------------------------------------------
# CSV I/O
# ---------------------------------------------------------------------------

def read_csv_dicts(path: Path) -> List[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv_dicts(path: Path, rows: List[dict], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def parse_epmc_record(rec: dict) -> dict:
    """Flatten an Europe PMC core-result record into our candidate-paper shape."""
    author_list = rec.get("authorList", {}).get("author", [])
    authors = "; ".join(
        a.get("fullName", "") for a in author_list if isinstance(a, dict)
    )
    journal = rec.get("journalInfo", {}).get("journal", {}).get("title", "")
    return {
        "title": rec.get("title", "").rstrip("."),
        "doi": rec.get("doi", ""),
        "pmid": rec.get("pmid", ""),
        "pmcid": rec.get("pmcid", ""),
        "year": rec.get("pubYear", ""),
        "journal": journal,
        "authors": authors,
        "abstract": rec.get("abstractText", ""),
        "is_open_access": rec.get("isOpenAccess", "N") == "Y",
        "pub_type_list": ", ".join(rec.get("pubTypeList", {}).get("pubType", [])) if isinstance(rec.get("pubTypeList"), dict) else "",
        "source": rec.get("source", ""),
        "epmc_id": rec.get("id", ""),
    }
