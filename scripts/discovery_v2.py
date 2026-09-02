# -*- coding: utf-8 -*-
"""Discovery strategies A-D (spec sections 6-10) against NCBI PubMed.

A: review-derived seeds, imported from the v1 pipeline's candidate_papers.csv
   (discovery_route containing "review_reference") -- reused, not rebuilt.
B: organism x technique OR-grouped PubMed search.
C: generic technique-first PubMed search (catches organisms reviews never mentioned).
D: explicit failure-language PubMed search.

Every hit's PMID becomes an efetch_pubmed_records() call to get real
title/abstract/doi/pmcid/year -- ESearch alone only returns bare UIDs.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from attempt_db import get_connection, upsert_paper
from common import DATA_DIR, env_int, read_csv_dicts
from ncbi_eutils import efetch_pubmed_records, esearch_pmids
from technique_vocabulary import (
    ALL_TECHNIQUE_PHRASES, FAILURE_DISCOVERY_PHRASES, GENERIC_DISCOVERY_PHRASES,
    NOVELTY_PHRASES, build_organism_technique_query,
)

MAX_PER_QUERY = env_int("GT2_MAX_PER_QUERY", 200)


def make_paper_id(pmid: str, doi: str) -> str:
    import hashlib
    basis = f"pmid:{pmid}" if pmid else f"doi:{doi.strip().lower()}"
    return "PV2" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def _ingest_pmids(conn, pmids: list[str], discovery_source: str, query: str) -> int:
    """Fetches real metadata for a batch of PMIDs and upserts them into
    the papers table. Returns how many were newly touched."""
    pmids = [p for p in pmids if p]
    if not pmids:
        return 0
    records = efetch_pubmed_records(pmids)
    n = 0
    for rec in records:
        if not rec.get("pmid") and not rec.get("doi"):
            continue
        paper_id = make_paper_id(rec.get("pmid", ""), rec.get("doi", ""))
        upsert_paper(
            conn, paper_id,
            pmid=rec.get("pmid", ""), doi=rec.get("doi", ""), pmcid=rec.get("pmcid", ""),
            title=rec.get("title", ""), abstract=rec.get("abstract", ""),
            journal=rec.get("journal", ""), year=rec.get("year", ""),
            discovery_sources=discovery_source, search_queries=query,
            processing_status="metadata_fetched",
        )
        n += 1
    conn.commit()
    return n


# ---------------------------------------------------------------------------
# Strategy A: review-derived seeds (reuses the v1 pipeline's own discovery)
# ---------------------------------------------------------------------------

def import_review_seeds(conn, limit: int | None = None) -> int:
    v1_candidates = read_csv_dicts(DATA_DIR / "candidate_papers.csv")
    review_derived = [
        p for p in v1_candidates
        if p.get("is_review") != "True" and "review_reference" in (p.get("discovery_route") or "")
    ]
    if limit:
        review_derived = review_derived[:limit]
    print(f"Importing {len(review_derived)} review-derived candidates from the v1 pipeline...")

    n = 0
    for p in review_derived:
        pmid = (p.get("pmid") or "").strip()
        doi = (p.get("doi") or "").strip()
        if not pmid and not doi:
            continue
        paper_id = make_paper_id(pmid, doi)
        upsert_paper(
            conn, paper_id, pmid=pmid, doi=doi, title=p.get("title", ""), journal=p.get("journal", ""),
            year=p.get("year", ""), discovery_sources="review", search_queries=p.get("discovery_query", ""),
            processing_status="discovered",
        )
        n += 1
        if n % 500 == 0:
            conn.commit()
            print(f"  ...{n}/{len(review_derived)}", flush=True)
    conn.commit()
    print(f"Done. {n} review-derived papers imported/merged as discovery_source=review.")
    return n


# ---------------------------------------------------------------------------
# Strategy B: organism x technique
# ---------------------------------------------------------------------------

def load_organism_list(organism_file: str | None = None) -> list[str]:
    """Builds the organism list from (1) organisms in review-derived
    papers' extracted observations, (2) organisms already in the v2 DB's
    engineering_attempts, (3) an optional manually-supplied file -- spec
    section 7."""
    organisms: set[str] = set()

    # From the v1 pipeline's own confirmed observations (manual + auto passes).
    for fname in ("manipulation_observations.csv", "manipulation_observations_auto.csv"):
        for row in read_csv_dicts(DATA_DIR / fname):
            name = (row.get("organism_name") or "").strip()
            if name and len(name.split()) <= 4:  # skip garbled/overlong multi-organism strings
                organisms.add(name)

    # From this v2 DB's own confirmed attempts (grows over repeated runs).
    conn = get_connection()
    try:
        for row in conn.execute("SELECT DISTINCT species FROM engineering_attempts WHERE species != ''"):
            organisms.add(row["species"])
    finally:
        conn.close()

    if organism_file and Path(organism_file).exists():
        for line in Path(organism_file).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                organisms.add(line)

    return sorted(organisms)


def discover_organism_technique(conn, organisms: list[str], max_results_per_organism: int = MAX_PER_QUERY) -> int:
    print(f"Strategy B: organism x technique search across {len(organisms)} organisms...")
    total = 0
    for i, organism in enumerate(organisms, start=1):
        query = build_organism_technique_query(organism, ALL_TECHNIQUE_PHRASES)
        pmids = esearch_pmids(query, max_results=max_results_per_organism)
        n = _ingest_pmids(conn, pmids, "organism_technique_search", query)
        total += n
        if i % 10 == 0 or i == len(organisms):
            print(f"  ...{i}/{len(organisms)} organisms searched ({total} papers ingested so far)", flush=True)
    print(f"Strategy B done. {total} papers ingested.")
    return total


# ---------------------------------------------------------------------------
# Strategy C: generic technique-first (organism-independent)
# ---------------------------------------------------------------------------

def discover_generic_technique(conn, max_results_per_phrase: int = MAX_PER_QUERY) -> int:
    phrases = GENERIC_DISCOVERY_PHRASES + NOVELTY_PHRASES
    print(f"Strategy C: generic technique-first search across {len(phrases)} phrases...")
    total = 0
    for i, phrase in enumerate(phrases, start=1):
        query = f'"{phrase}"' if " " in phrase else phrase
        pmids = esearch_pmids(query, max_results=max_results_per_phrase)
        n = _ingest_pmids(conn, pmids, "generic_technique_search", query)
        total += n
        print(f"  [{i}/{len(phrases)}] {phrase!r} -> {len(pmids)} hits ({total} ingested so far)", flush=True)
    print(f"Strategy C done. {total} papers ingested.")
    return total


# ---------------------------------------------------------------------------
# Strategy D: explicit failure language
# ---------------------------------------------------------------------------

def discover_failure_language(conn, max_results_per_phrase: int = MAX_PER_QUERY) -> int:
    print(f"Strategy D: failure-language search across {len(FAILURE_DISCOVERY_PHRASES)} phrases...")
    total = 0
    for i, phrase in enumerate(FAILURE_DISCOVERY_PHRASES, start=1):
        query = f'"{phrase}"'
        pmids = esearch_pmids(query, max_results=max_results_per_phrase)
        n = _ingest_pmids(conn, pmids, "failure_phrase_search", query)
        total += n
        print(f"  [{i}/{len(FAILURE_DISCOVERY_PHRASES)}] {phrase!r} -> {len(pmids)} hits ({total} ingested so far)", flush=True)
    print(f"Strategy D done. {total} papers ingested.")
    return total


def run_all(organism_file: str | None = None, max_papers: int | None = None) -> None:
    conn = get_connection()
    try:
        import_review_seeds(conn, limit=max_papers)
        organisms = load_organism_list(organism_file)
        per_query_cap = max_papers or MAX_PER_QUERY
        discover_organism_technique(conn, organisms, max_results_per_organism=per_query_cap)
        discover_generic_technique(conn, max_results_per_phrase=per_query_cap)
        discover_failure_language(conn, max_results_per_phrase=per_query_cap)
    finally:
        conn.close()


if __name__ == "__main__":
    run_all()
