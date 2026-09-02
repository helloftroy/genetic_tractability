# -*- coding: utf-8 -*-
"""NCBI E-utilities client: ESearch, ESummary, EFetch, ELink.

Primary literature-discovery infrastructure for the v2 (NCBI/PubMed/PMC)
pipeline -- deliberately NOT OpenAlex (see run_engineering_discovery.py's
module docstring for why). Rate-limited to NCBI's own documented policy
(3 req/s without an API key, 10/s with one -- see common.py's
_HOST_MIN_INTERVAL, confirmed live against a real 429 from the BioC
endpoint), cached on disk via common.py's cached_get_json/cached_get_text,
retried with backoff (inherited from cached_get_json/text).

Batching: ESummary/EFetch accept comma-joined ID lists (NCBI's own
recommended batching -- avoids one HTTP call per paper), capped at 200
IDs/call per NCBI's posted guidance. ESearch pagination uses retstart/
retmax directly rather than WebEnv/history plumbing -- simpler and
sufficient at this project's query sizes (hundreds-to-low-thousands of
hits per query, not the 100,000+ scale history exists for), capped by
max_results to keep any single query bounded.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import urllib.parse

from common import NCBI_API_KEY, NCBI_EMAIL, NCBI_TOOL, cached_get_json, cached_get_text

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _base_params() -> dict:
    params = {"email": NCBI_EMAIL, "tool": NCBI_TOOL}
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    return params


def esearch_count(term: str, db: str = "pubmed") -> int:
    """Just the hit count for a term -- cheap way to size a query before
    deciding how deep to paginate."""
    params = {**_base_params(), "db": db, "term": term, "retmode": "json", "retmax": 0}
    url = f"{EUTILS_BASE}/esearch.fcgi?{urllib.parse.urlencode(params)}"
    data = cached_get_json(url, "ncbi_eutils")
    if not data:
        return 0
    try:
        return int(data.get("esearchresult", {}).get("count", 0))
    except (TypeError, ValueError):
        return 0


def esearch_pmids(term: str, db: str = "pubmed", max_results: int = 500, page_size: int = 200) -> list[str]:
    """Paginated ESearch, returns up to max_results PMIDs (or other db's
    UIDs) for a term via retstart/retmax."""
    pmids: list[str] = []
    retstart = 0
    while len(pmids) < max_results:
        batch = min(page_size, max_results - len(pmids))
        params = {
            **_base_params(), "db": db, "term": term, "retmode": "json",
            "retmax": batch, "retstart": retstart, "sort": "relevance",
        }
        url = f"{EUTILS_BASE}/esearch.fcgi?{urllib.parse.urlencode(params)}"
        data = cached_get_json(url, "ncbi_eutils")
        if not data:
            break
        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids:
            break
        pmids.extend(ids)
        retstart += len(ids)
        if len(ids) < batch:
            break  # exhausted the result set
    return pmids[:max_results]


def _text(el: Optional[ET.Element]) -> str:
    if el is None:
        return ""
    return " ".join("".join(el.itertext()).split())


def _parse_pubmed_article(article: ET.Element) -> dict:
    medline = article.find("MedlineCitation")
    pmid_el = medline.find("PMID") if medline is not None else None
    pmid = (pmid_el.text or "").strip() if pmid_el is not None else ""

    article_el = medline.find("Article") if medline is not None else None
    title = _text(article_el.find("ArticleTitle")) if article_el is not None else ""

    abstract_parts = []
    if article_el is not None:
        for ab_text in article_el.findall(".//Abstract/AbstractText"):
            label = ab_text.get("Label")
            piece = _text(ab_text)
            abstract_parts.append(f"{label}: {piece}" if label else piece)
    abstract = " ".join(abstract_parts)

    journal_el = article_el.find("Journal") if article_el is not None else None
    journal = _text(journal_el.find("Title")) if journal_el is not None else ""

    year = ""
    if journal_el is not None:
        pub_date = journal_el.find(".//JournalIssue/PubDate")
        if pub_date is not None:
            year_el = pub_date.find("Year")
            if year_el is not None and year_el.text:
                year = year_el.text.strip()
            else:
                medline_date = pub_date.find("MedlineDate")
                if medline_date is not None and medline_date.text:
                    year = (medline_date.text.strip().split()[:1] or [""])[0]

    pub_types = [_text(pt) for pt in (article_el.findall(".//PublicationTypeList/PublicationType") if article_el is not None else [])]

    doi = ""
    pmcid = ""
    for aid in article.findall(".//PubmedData/ArticleIdList/ArticleId"):
        id_type = aid.get("IdType", "")
        if id_type == "doi":
            doi = (aid.text or "").strip()
        elif id_type == "pmc":
            pmcid = (aid.text or "").strip()

    authors = []
    for author in (article_el.findall(".//AuthorList/Author") if article_el is not None else []):
        last = _text(author.find("LastName"))
        fore = _text(author.find("ForeName"))
        if last:
            authors.append(f"{last} {fore}".strip())

    return {
        "pmid": pmid, "doi": doi, "pmcid": pmcid, "title": title, "abstract": abstract,
        "journal": journal, "year": year, "pub_types": pub_types, "authors": "; ".join(authors),
    }


def efetch_pubmed_records(pmids: list[str], batch_size: int = 200) -> list[dict]:
    """Batched EFetch (rettype=abstract, retmode=xml) -- the only way to
    get real abstract text; ESummary is bibliographic metadata only, no
    abstract. Returns one dict per PMID (parsed from PubmedArticleSet
    XML): pmid, doi, pmcid, title, abstract, journal, year, pub_types,
    authors."""
    records: list[dict] = []
    for i in range(0, len(pmids), batch_size):
        chunk = pmids[i:i + batch_size]
        params = {**_base_params(), "db": "pubmed", "id": ",".join(chunk), "rettype": "abstract", "retmode": "xml"}
        url = f"{EUTILS_BASE}/efetch.fcgi?{urllib.parse.urlencode(params)}"
        xml_text = cached_get_text(url, "ncbi_eutils")
        if not xml_text:
            continue
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            continue
        for article in root.findall(".//PubmedArticle"):
            records.append(_parse_pubmed_article(article))
    return records


# ELink names for PubMed-to-PubMed citation graph traversal:
#   pubmed_pubmed_citedin -- papers that CITE the given PMID (forward)
#   pubmed_pubmed_refs    -- papers CITED BY the given PMID (backward,
#                             only populated for PMC-indexed reference
#                             lists -- not every PubMed record has this)
LINKNAME_CITED_BY = "pubmed_pubmed_citedin"
LINKNAME_REFERENCES = "pubmed_pubmed_refs"


def elink(pmid: str, linkname: str, db: str = "pubmed") -> list[str]:
    """One ELink call for one source PMID -- returns linked PMIDs (empty
    list if none, e.g. a paper with no indexed reference list for
    LINKNAME_REFERENCES)."""
    params = {**_base_params(), "dbfrom": "pubmed", "db": db, "id": pmid, "linkname": linkname, "retmode": "json"}
    url = f"{EUTILS_BASE}/elink.fcgi?{urllib.parse.urlencode(params)}"
    data = cached_get_json(url, "ncbi_eutils")
    if not data:
        return []
    linked_ids: list[str] = []
    for linkset in data.get("linksets", []):
        for linksetdb in linkset.get("linksetdbs", []):
            linked_ids.extend(linksetdb.get("links", []))
    return linked_ids
