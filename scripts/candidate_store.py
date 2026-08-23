"""Append-and-dedupe store for candidate_papers.csv.

Dedup key priority: DOI, then PMID, then normalized title (per spec section 4).
When a paper is rediscovered via a new route, the earliest discovery_route is
kept but discovery_query/notes are appended so the paper's full discovery
history isn't lost.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from common import DATA_DIR, make_paper_id, normalize_doi, normalize_title, read_csv_dicts, write_csv_dicts

CANDIDATE_PAPERS_PATH = DATA_DIR / "candidate_papers.csv"

FIELDNAMES = [
    "paper_id",
    "title",
    "doi",
    "pmid",
    "pmcid",
    "year",
    "journal",
    "authors",
    "source_database",
    "discovery_route",
    "discovery_query",
    "review_seed_doi",
    "is_review",
    "full_text_available",
    "processing_status",
    "notes",
]


class CandidateStore:
    def __init__(self) -> None:
        self._rows: Dict[str, dict] = {}
        self._by_doi: Dict[str, str] = {}
        self._by_pmid: Dict[str, str] = {}
        self._by_title: Dict[str, str] = {}
        for row in read_csv_dicts(CANDIDATE_PAPERS_PATH):
            self._index(row)

    def _index(self, row: dict) -> None:
        pid = row["paper_id"]
        self._rows[pid] = row
        doi = normalize_doi(row.get("doi"))
        if doi:
            self._by_doi[doi] = pid
        pmid = (row.get("pmid") or "").strip()
        if pmid:
            self._by_pmid[pmid] = pid
        title = normalize_title(row.get("title"))
        if title:
            self._by_title[title] = pid

    def _find_existing(self, doi: str, pmid: str, title: str) -> Optional[str]:
        ndoi = normalize_doi(doi)
        if ndoi and ndoi in self._by_doi:
            return self._by_doi[ndoi]
        if pmid and pmid in self._by_pmid:
            return self._by_pmid[pmid]
        ntitle = normalize_title(title)
        if ntitle and ntitle in self._by_title:
            return self._by_title[ntitle]
        return None

    def add(
        self,
        *,
        title: str,
        doi: str = "",
        pmid: str = "",
        pmcid: str = "",
        year: str = "",
        journal: str = "",
        authors: str = "",
        source_database: str = "europe_pmc",
        discovery_route: str,
        discovery_query: str = "",
        review_seed_doi: str = "",
        is_review: bool = False,
        full_text_available: bool = False,
        processing_status: str = "discovered",
        notes: str = "",
    ) -> str:
        existing_id = self._find_existing(doi, pmid, title)
        if existing_id:
            row = self._rows[existing_id]
            # Enrich blank fields, and record the additional discovery route.
            for field, value in (
                ("doi", doi), ("pmid", pmid), ("pmcid", pmcid),
                ("year", year), ("journal", journal), ("authors", authors),
            ):
                if value and not row.get(field):
                    row[field] = value
            if str(is_review) == "True" or is_review:
                row["is_review"] = "True"
            if full_text_available and row.get("full_text_available") != "True":
                row["full_text_available"] = "True"
            existing_routes = set(x.strip() for x in row.get("discovery_route", "").split("|") if x.strip())
            existing_routes.add(discovery_route)
            row["discovery_route"] = "|".join(sorted(existing_routes))
            if discovery_query and discovery_query not in row.get("discovery_query", ""):
                sep = " || " if row.get("discovery_query") else ""
                row["discovery_query"] = f"{row.get('discovery_query', '')}{sep}{discovery_query}"[:2000]
            if review_seed_doi and review_seed_doi not in row.get("review_seed_doi", ""):
                sep = "; " if row.get("review_seed_doi") else ""
                row["review_seed_doi"] = f"{row.get('review_seed_doi', '')}{sep}{review_seed_doi}"
            if notes:
                sep = " || " if row.get("notes") else ""
                row["notes"] = f"{row.get('notes', '')}{sep}{notes}"[:2000]
            self._index(row)
            return existing_id

        paper_id = make_paper_id(doi, pmid, title)
        row = {
            "paper_id": paper_id,
            "title": title,
            "doi": doi,
            "pmid": pmid,
            "pmcid": pmcid,
            "year": year,
            "journal": journal,
            "authors": authors,
            "source_database": source_database,
            "discovery_route": discovery_route,
            "discovery_query": discovery_query,
            "review_seed_doi": review_seed_doi,
            "is_review": "True" if is_review else "False",
            "full_text_available": "True" if full_text_available else "False",
            "processing_status": processing_status,
            "notes": notes,
        }
        self._index(row)
        return paper_id

    def get(self, paper_id: str) -> Optional[dict]:
        return self._rows.get(paper_id)

    def set_status(self, paper_id: str, status: str) -> None:
        if paper_id in self._rows:
            self._rows[paper_id]["processing_status"] = status

    def all_rows(self) -> List[dict]:
        return list(self._rows.values())

    def save(self) -> None:
        rows = sorted(self._rows.values(), key=lambda r: (r.get("year") or "", r["paper_id"]))
        write_csv_dicts(CANDIDATE_PAPERS_PATH, rows, FIELDNAMES)
