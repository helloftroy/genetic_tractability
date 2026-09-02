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

# NCBI-specific config (spec: "Configuration should support NCBI_EMAIL,
# NCBI_TOOL, NCBI_API_KEY. Do not hard-code credentials.") -- these are
# separate from the generic CONTACT_EMAIL above so an NCBI-registered
# email/tool name can differ from this pipeline's generic Europe PMC
# contact, but default to it when NCBI_EMAIL isn't explicitly set.
NCBI_EMAIL = os.environ.get("NCBI_EMAIL", CONTACT_EMAIL)
NCBI_TOOL = os.environ.get("NCBI_TOOL", "genetic-tractability-discovery")


def env_int(name: str, default: int) -> int:
    """Reads an integer discovery-depth knob from the environment (e.g. so
    `sbatch --export=ALL,GT_BROAD_PER_QUERY=800 cluster/run_discovery.sbatch`
    controls it directly), falling back to `default` when unset."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"Environment variable {name}={raw!r} is not a valid integer")

EPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
NCBI_EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})

_last_request_time: Dict[str, float] = {}
_MIN_INTERVAL = 0.2  # default: ~5 req/s, fine for Europe PMC and OpenAlex

# NCBI's documented E-utilities limit is 3 req/s without an API key, 10/s
# with one -- confirmed live: a request fired right after another (using
# the old shared 0.2s/5-per-sec default) got a real 429 "Maximum 3
# requests per second per user" from the BioC endpoint. This applies to
# ALL NCBI hosts (E-utilities and BioC alike, same backend), so both the
# old ncbi_esearch/ncbi_esummary (genome matching) and the new
# ncbi_eutils.py/pmc_bioc.py modules share this same, correctly-slower
# throttle bucket rather than each guessing independently.
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")
_HOST_MIN_INTERVAL = {
    "ncbi": 0.11 if NCBI_API_KEY else 0.34,
    "ncbi_eutils": 0.11 if NCBI_API_KEY else 0.34,
    "ncbi_bioc": 0.11 if NCBI_API_KEY else 0.34,
}


def _throttle(host: str) -> None:
    interval = _HOST_MIN_INTERVAL.get(host, _MIN_INTERVAL)
    now = time.time()
    last = _last_request_time.get(host, 0.0)
    wait = interval - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_request_time[host] = time.time()


def _cache_path(url: str) -> Path:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{key}.json"


# The GPU/vLLM cluster stage (run_extraction.sbatch) deliberately runs with
# no internet access -- that's the whole point of run_prefetch.sbatch
# warming the cache first. But scripts 13/14 call the same
# epmc_lookup_record()/epmc_fulltext_xml() functions regardless of which
# stage is running, so if a paper's batch was never actually prefetched
# (e.g. a later run_extraction.sbatch was submitted with a bigger
# BATCH_SIZE, or against a candidate pool that grew, without a matching
# run_prefetch.sbatch run first), a cache miss here silently burns through
# 3 retries x 30s timeout each (~90s+) before giving up -- confirmed live:
# a real run spent ~45 minutes on 20 papers, 18 of them "no abstract"
# (really just a cache miss timing out, not Europe PMC lacking an
# abstract). run_extraction.sbatch sets this env var so a cache miss there
# fails INSTANTLY instead of hanging, turning an hours-long silent stall
# into an immediately visible, correctly-labeled skip.
CACHE_ONLY = os.environ.get("GENETIC_TRACTABILITY_CACHE_ONLY", "") == "1"
_cache_only_misses = 0


def cached_get_json(url: str, host_key: str, retries: int = 3) -> Optional[dict]:
    global _cache_only_misses
    cache_path = _cache_path(url)
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except Exception:
            pass
    if CACHE_ONLY:
        _cache_only_misses += 1
        return None
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


def peek_cached_json(url: str) -> Optional[dict]:
    """Reads a URL's cached response if present, WITHOUT ever attempting a
    network fetch (unlike cached_get_json, which falls back to fetching
    unless CACHE_ONLY happens to be set) -- for reporting scripts that must
    stay network-free regardless of what environment they're run in."""
    cache_path = _cache_path(url)
    if not cache_path.exists():
        return None
    try:
        return json.loads(cache_path.read_text())
    except Exception:
        return None


def cache_only_miss_count() -> int:
    """How many URLs were skipped (not fetched) because CACHE_ONLY is set
    and they weren't already warm -- call this at the end of a script and
    print it, so an under-prefetched batch is immediately visible instead
    of silently showing up as a pile of "no abstract available" rows."""
    return _cache_only_misses


def cached_get_text(url: str, host_key: str, retries: int = 3) -> Optional[str]:
    global _cache_only_misses
    cache_key = _cache_path(url).with_suffix(".txt")
    if cache_key.exists():
        return cache_key.read_text()
    if CACHE_ONLY:
        _cache_only_misses += 1
        return None
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


def cached_get_binary(url: str, host_key: str, retries: int = 2, timeout: int = 60) -> Optional[bytes]:
    """Like cached_get_text but for binary content (PDFs). Never retried as
    aggressively as the JSON/text fetchers -- a PDF fetch failure is far
    more likely to be a real, permanent block (publisher bot-detection,
    e.g. confirmed live: Wiley 403s a plain request even to a paper
    OpenAlex itself marks fully open-access) than a transient network
    blip, so this doesn't burn retries chasing something that won't
    change. A 403/publisher block is treated the same as 404 -- this
    paper just stays unfetchable, not an error worth retrying."""
    global _cache_only_misses
    cache_key = _cache_path(url).with_suffix(".pdf")
    if cache_key.exists():
        return cache_key.read_bytes()
    if CACHE_ONLY:
        _cache_only_misses += 1
        return None
    for attempt in range(retries):
        _throttle(host_key)
        try:
            resp = _session.get(url, timeout=timeout)
            if resp.status_code == 200 and resp.content:
                cache_key.write_bytes(resp.content)
                return resp.content
            if resp.status_code in (403, 404):
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


def epmc_fulltext_url(pmcid: str) -> str:
    return f"{EPMC_BASE}/{pmcid}/fullTextXML"


def epmc_fulltext_xml(pmcid: str) -> Optional[str]:
    return cached_get_text(epmc_fulltext_url(pmcid), "epmc")


def epmc_lookup_url(doi: str = "", pmid: str = "", title: str = "") -> Optional[str]:
    if doi:
        query = f'DOI:"{normalize_doi(doi)}"'
    elif pmid:
        query = f"EXT_ID:{pmid} AND SRC:MED"
    elif title:
        query = f'TITLE:"{title}"'
    else:
        return None
    return f"{EPMC_BASE}/search?{urllib.parse.urlencode({'query': query, 'format': 'json', 'resultType': 'core', 'pageSize': 1})}"


def epmc_lookup_record(doi: str = "", pmid: str = "", title: str = "") -> Optional[dict]:
    """Fetch one full Europe PMC core record (title/abstract/OA status/pmcid/...)."""
    url = epmc_lookup_url(doi, pmid, title)
    if not url:
        return None
    data = cached_get_json(url, "epmc")
    if not data:
        return None
    results = data.get("resultList", {}).get("result", [])
    if not results:
        return None
    return parse_epmc_record(results[0])


def is_cached(url: Optional[str], kind: str = "json") -> bool:
    """Checks whether a URL is already warm in the on-disk cache, WITHOUT
    making any network call or touching CACHE_ONLY's miss counter -- for
    reporting/auditing "how much of the pending backlog is already
    fetched" without attempting to fetch anything."""
    if not url:
        return False
    path = _cache_path(url)
    if kind == "text":
        path = path.with_suffix(".txt")
    elif kind == "pdf":
        path = path.with_suffix(".pdf")
    return path.exists()


# ---------------------------------------------------------------------------
# OpenAlex (open-access PDF fallback -- Europe PMC's fullTextXML only covers
# papers PMC itself has deposited full text for; OpenAlex's own OA detection
# (Unpaywall-backed) is broader and catches genuinely open-access papers
# hosted on a publisher's own site, a preprint server, or an institutional
# repository that never went through PMC at all. Mirrors fair_ocean_agent's
# own _auto_fetch_open_access_pdf design (workflow/handlers.py) -- confirmed
# live there and re-confirmed here against a real paper this pipeline had
# marked not-open-access: OpenAlex correctly showed is_oa=True with a direct
# PDF link on the publisher's own site.
# ---------------------------------------------------------------------------

OPENALEX_BASE = "https://api.openalex.org"


def openalex_best_oa_pdf_url(doi: str) -> Optional[str]:
    """Returns a real, directly-downloadable PDF URL if OpenAlex marks this
    DOI genuinely open access, else None. Never spoofs a browser User-Agent
    to get past a publisher's bot-detection -- a block (403) is a real,
    deliberate access decision, not a bug to route around; that paper just
    stays unfetchable, exactly as before this fallback existed."""
    if not doi:
        return None
    url = f"{OPENALEX_BASE}/works/https://doi.org/{normalize_doi(doi)}"
    data = cached_get_json(url, "openalex")
    if not data:
        return None
    best_oa = data.get("best_oa_location") or {}
    pdf_url = best_oa.get("pdf_url")
    if best_oa.get("is_oa") and pdf_url:
        return pdf_url
    return None


def pdf_bytes_to_text(content: bytes) -> str:
    """Plain-text extraction via pypdf -- deliberately simple (no per-page
    layout-mode comparison or repeated-header/footer stripping, unlike
    fair_ocean_agent's extraction/pdf.py): this pipeline only needs
    keyword-taggable sentences, not a pixel-perfect reading order, so the
    added complexity isn't worth it here."""
    import io

    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# NCBI E-utilities (genome assembly lookup)
# ---------------------------------------------------------------------------

def _ncbi_base_params() -> dict:
    params = {"email": NCBI_EMAIL, "tool": NCBI_TOOL}
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    return params


def ncbi_esearch(db: str, term: str, retmax: int = 20) -> List[str]:
    params = {**_ncbi_base_params(), "db": db, "term": term, "retmode": "json", "retmax": retmax}
    url = f"{NCBI_EUTILS_BASE}/esearch.fcgi?{urllib.parse.urlencode(params)}"
    data = cached_get_json(url, "ncbi")
    if not data:
        return []
    return data.get("esearchresult", {}).get("idlist", [])


def ncbi_esummary(db: str, ids: List[str]) -> dict:
    if not ids:
        return {}
    params = {**_ncbi_base_params(), "db": db, "id": ",".join(ids), "retmode": "json"}
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


def locked_merge_write_csv(
    path: Path,
    fieldnames: List[str],
    key: str = "paper_id",
    upsert_rows: Optional[List[dict]] = None,
    remove_ids: Optional[Iterable[str]] = None,
) -> None:
    """Safely applies an add/replace-by-key and/or remove-by-key update to
    a shared CSV, re-reading the file fresh under an exclusive lock right
    before merging -- NOT against a long-held in-memory snapshot from
    earlier in the caller's run.

    Exists because abstract_triage.csv is written by two different
    processes that can legitimately run at the same time (script 13,
    adding new triage decisions, and script 20, removing healed rows) --
    each blindly overwriting the whole file from its own stale snapshot
    would silently discard whatever the other one had just written (a
    lost-update race, confirmed as a real risk once script 20 started
    writing to the same file script 13 does). Every writer of a
    concurrently-shared pipeline CSV should go through this, not
    write_csv_dicts() directly.

    fcntl.flock is POSIX-only (fine here: Mac + Linux HPC, no Windows
    target for this project).
    """
    import fcntl

    upsert_rows = upsert_rows or []
    remove_ids = set(remove_ids or [])
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.touch(exist_ok=True)
    with open(lock_path, "r+") as lockfile:
        fcntl.flock(lockfile.fileno(), fcntl.LOCK_EX)
        try:
            current = {r[key]: r for r in read_csv_dicts(path) if key in r}
            for row in upsert_rows:
                current[row[key]] = row
            for rid in remove_ids:
                current.pop(rid, None)
            write_csv_dicts(path, list(current.values()), fieldnames)
        finally:
            fcntl.flock(lockfile.fileno(), fcntl.LOCK_UN)


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
