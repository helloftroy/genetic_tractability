# -*- coding: utf-8 -*-
"""SQLite schema for the v2 (NCBI/PubMed/PMC) pipeline: two tables per
spec section 25 -- `papers` and `engineering_attempts`.

Deliberately SQLite, not more CSVs: the v1 pipeline (scripts 01-21) hit a
real, repeated class of bugs from CSV read-whole-file/modify-in-memory/
write-whole-file-back being done by multiple concurrent processes
(abstract_triage.csv's lost-update race between scripts 13 and 20; the
keyword_spans_index.csv checkpoint gap that left real packets invisible
after a job died mid-run). SQLite's own transactions and WAL mode solve
that whole class of problem for free, and a real `processing_status`
column with indexed WHERE-clause queries is a much more direct fit for
spec section 35's resumability requirements than set-difference logic
across multiple CSVs.

Raw API/full-text responses still live on disk as before (common.py's
data/cache/), per spec section 25's "Raw API/full-text files can live on
disk."
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR

DB_PATH = DATA_DIR / "tractability.db"

# processing_status vocabulary, per spec section 35 -- a paper moves
# forward through these (not necessarily hitting every one: a paper with
# no PMCID skips straight from metadata_fetched to screened_* using
# abstract-only text).
PAPER_STATUSES = [
    "discovered", "metadata_fetched", "fulltext_fetched", "screened_irrelevant",
    "screened_relevant", "extraction_complete", "needs_review", "fulltext_unavailable",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    paper_id TEXT PRIMARY KEY,
    pmid TEXT,
    pmcid TEXT,
    doi TEXT,
    title TEXT,
    abstract TEXT,
    journal TEXT,
    year TEXT,
    fulltext_status TEXT DEFAULT 'not_checked',
    discovery_sources_json TEXT DEFAULT '[]',
    source_seed_pmids_json TEXT DEFAULT '[]',
    search_queries_json TEXT DEFAULT '[]',
    candidate_score REAL DEFAULT 0,
    processing_status TEXT DEFAULT 'discovered',
    first_seen_at TEXT,
    last_checked_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_pmid ON papers(pmid) WHERE pmid IS NOT NULL AND pmid != '';
CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(processing_status);
CREATE INDEX IF NOT EXISTS idx_papers_score ON papers(candidate_score);

CREATE TABLE IF NOT EXISTS engineering_attempts (
    attempt_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL REFERENCES papers(paper_id),

    organism_name_raw TEXT,
    genus TEXT,
    species TEXT,
    strain TEXT,
    strain_accession TEXT,
    culture_collection_accession TEXT,

    wild_type_status TEXT DEFAULT 'unclear',

    technique_raw TEXT,
    technique_normalized TEXT,

    vector_or_construct TEXT,
    plasmid_name TEXT,
    delivery_method TEXT,
    selection_method TEXT,
    attempt_conditions_summary TEXT,

    outcome TEXT DEFAULT 'unclear',
    outcome_detail TEXT,
    failure_reason TEXT,
    failure_reason_raw TEXT,

    quantitative_efficiency TEXT,
    quantitative_efficiency_unit TEXT,

    evidence_method TEXT,
    evidence_result TEXT,

    methods_chunk_ids TEXT DEFAULT '[]',
    results_chunk_ids TEXT DEFAULT '[]',
    supplement_chunk_ids TEXT DEFAULT '[]',

    llm_confidence REAL,
    needs_review INTEGER DEFAULT 0,

    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_attempts_paper ON engineering_attempts(paper_id);
CREATE INDEX IF NOT EXISTS idx_attempts_outcome ON engineering_attempts(outcome);
CREATE INDEX IF NOT EXISTS idx_attempts_wt ON engineering_attempts(wild_type_status);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")  # real concurrent reader/writer support across processes
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def upsert_paper(conn: sqlite3.Connection, paper_id: str, **fields: Any) -> None:
    """Insert a new paper, or merge new fields into an existing one --
    discovery_sources/source_seed_pmids/search_queries are UNIONED (a
    paper found by multiple strategies keeps every source, per spec
    section 36), never overwritten. Scalar fields (title, abstract, ...)
    fill in only if not already set, so a later, less-complete discovery
    hit never clobbers richer data an earlier fetch already recorded."""
    existing = conn.execute("SELECT * FROM papers WHERE paper_id = ?", (paper_id,)).fetchone()
    ts = now_iso()

    if existing is None:
        row = {
            "paper_id": paper_id, "pmid": "", "pmcid": "", "doi": "", "title": "", "abstract": "",
            "journal": "", "year": "", "fulltext_status": "not_checked",
            "discovery_sources_json": "[]", "source_seed_pmids_json": "[]", "search_queries_json": "[]",
            "candidate_score": 0.0, "processing_status": "discovered",
            "first_seen_at": ts, "last_checked_at": ts,
        }
    else:
        row = dict(existing)
        row["last_checked_at"] = ts

    for list_field in ("discovery_sources", "source_seed_pmids", "search_queries"):
        json_field = f"{list_field}_json"
        if list_field in fields:
            current = set(json.loads(row.get(json_field) or "[]"))
            incoming = fields.pop(list_field)
            incoming = [incoming] if isinstance(incoming, str) else incoming
            current.update(incoming)
            row[json_field] = json.dumps(sorted(current))

    for key, value in fields.items():
        if key not in row:
            continue
        if existing is not None and row.get(key) and not value:
            continue  # don't clobber existing non-empty value with an empty one
        row[key] = value

    columns = list(row.keys())
    placeholders = ", ".join(f":{c}" for c in columns)
    updates = ", ".join(f"{c}=excluded.{c}" for c in columns if c != "paper_id")
    conn.execute(
        f"INSERT INTO papers ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(paper_id) DO UPDATE SET {updates}",
        row,
    )


def get_paper(conn: sqlite3.Connection, paper_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM papers WHERE paper_id = ?", (paper_id,)).fetchone()


def find_paper_id_by_identifier(conn: sqlite3.Connection, pmid: str = "", doi: str = "") -> Optional[str]:
    if pmid:
        row = conn.execute("SELECT paper_id FROM papers WHERE pmid = ?", (pmid,)).fetchone()
        if row:
            return row["paper_id"]
    if doi:
        row = conn.execute("SELECT paper_id FROM papers WHERE doi = ?", (doi,)).fetchone()
        if row:
            return row["paper_id"]
    return None


def papers_by_status(conn: sqlite3.Connection, statuses: Iterable[str], limit: Optional[int] = None) -> list[sqlite3.Row]:
    placeholders = ", ".join("?" for _ in statuses)
    sql = f"SELECT * FROM papers WHERE processing_status IN ({placeholders}) ORDER BY candidate_score DESC, first_seen_at ASC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, list(statuses)).fetchall()


def insert_attempt(conn: sqlite3.Connection, attempt_id: str, paper_id: str, **fields: Any) -> None:
    row = {
        "attempt_id": attempt_id, "paper_id": paper_id, "organism_name_raw": "", "genus": "", "species": "",
        "strain": "", "strain_accession": "", "culture_collection_accession": "",
        "wild_type_status": "unclear", "technique_raw": "", "technique_normalized": "",
        "vector_or_construct": "", "plasmid_name": "", "delivery_method": "", "selection_method": "",
        "attempt_conditions_summary": "", "outcome": "unclear", "outcome_detail": "",
        "failure_reason": "", "failure_reason_raw": "", "quantitative_efficiency": "",
        "quantitative_efficiency_unit": "", "evidence_method": "", "evidence_result": "",
        "methods_chunk_ids": "[]", "results_chunk_ids": "[]", "supplement_chunk_ids": "[]",
        "llm_confidence": None, "needs_review": 0, "created_at": now_iso(),
    }
    row.update(fields)
    for list_field in ("methods_chunk_ids", "results_chunk_ids", "supplement_chunk_ids"):
        if isinstance(row[list_field], list):
            row[list_field] = json.dumps(row[list_field])
    columns = list(row.keys())
    placeholders = ", ".join(f":{c}" for c in columns)
    conn.execute(
        f"INSERT OR REPLACE INTO engineering_attempts ({', '.join(columns)}) VALUES ({placeholders})",
        row,
    )


if __name__ == "__main__":
    init_db()
    print(f"Initialized {DB_PATH}")
