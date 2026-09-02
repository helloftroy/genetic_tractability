# -*- coding: utf-8 -*-
"""Report generation (spec section 37) -- CSV exports + summary stats from
the SQLite DB. Success metric is deliberately NOT "papers found" (spec
section 38): the headline numbers are distinct strain x technique
attempts, and specifically how many are explicit FAILURES, since that's
the whole point of this pipeline (spec section 40)."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from attempt_db import get_connection
from common import DATA_DIR

REPORTS_DIR = DATA_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _write_query(conn, filename: str, sql: str, params: tuple = ()) -> int:
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        (REPORTS_DIR / filename).write_text("")
        return 0
    fieldnames = rows[0].keys()
    with (REPORTS_DIR / filename).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(dict(r))
    return len(rows)


def generate_reports(conn) -> None:
    counts = {}
    counts["discovered_papers.csv"] = _write_query(
        conn, "discovered_papers.csv",
        "SELECT paper_id, pmid, pmcid, doi, title, journal, year, fulltext_status, "
        "discovery_sources_json, candidate_score, processing_status FROM papers "
        "ORDER BY candidate_score DESC")
    counts["high_priority_candidates.csv"] = _write_query(
        conn, "high_priority_candidates.csv",
        "SELECT paper_id, pmid, pmcid, doi, title, candidate_score, processing_status FROM papers "
        "WHERE processing_status IN ('screened_relevant','extraction_complete') ORDER BY candidate_score DESC")
    counts["fulltext_unavailable.csv"] = _write_query(
        conn, "fulltext_unavailable.csv",
        "SELECT paper_id, pmid, doi, title, journal, year FROM papers WHERE fulltext_status='unavailable_from_pmc'")
    counts["engineering_attempts.csv"] = _write_query(
        conn, "engineering_attempts.csv",
        "SELECT a.*, p.pmid, p.pmcid, p.doi, p.title AS paper_title FROM engineering_attempts a "
        "JOIN papers p ON p.paper_id = a.paper_id ORDER BY a.paper_id, a.attempt_id")
    counts["failures.csv"] = _write_query(
        conn, "failures.csv",
        "SELECT a.*, p.pmid, p.doi, p.title AS paper_title FROM engineering_attempts a "
        "JOIN papers p ON p.paper_id = a.paper_id WHERE a.outcome='failure'")
    counts["successes.csv"] = _write_query(
        conn, "successes.csv",
        "SELECT a.*, p.pmid, p.doi, p.title AS paper_title FROM engineering_attempts a "
        "JOIN papers p ON p.paper_id = a.paper_id WHERE a.outcome='success'")
    counts["partial_successes.csv"] = _write_query(
        conn, "partial_successes.csv",
        "SELECT a.*, p.pmid, p.doi, p.title AS paper_title FROM engineering_attempts a "
        "JOIN papers p ON p.paper_id = a.paper_id WHERE a.outcome='partial_success'")
    counts["needs_review.csv"] = _write_query(
        conn, "needs_review.csv",
        "SELECT a.*, p.pmid, p.doi, p.title AS paper_title FROM engineering_attempts a "
        "JOIN papers p ON p.paper_id = a.paper_id WHERE a.needs_review=1")

    for name, n in counts.items():
        print(f"  {REPORTS_DIR / name}: {n} rows")


def print_summary(conn) -> None:
    print("=" * 72)
    print("SUMMARY (spec section 37/38 -- attempts and failures matter more than paper count)")
    print("=" * 72)

    total_papers = conn.execute("SELECT COUNT(*) c FROM papers").fetchone()["c"]
    print(f"\nPapers discovered by strategy:")
    for row in conn.execute("SELECT discovery_sources_json, COUNT(*) c FROM papers GROUP BY discovery_sources_json"):
        pass  # discovery_sources_json can hold multiple sources per paper; tally properly below
    import json
    from collections import Counter
    source_counts = Counter()
    for row in conn.execute("SELECT discovery_sources_json FROM papers"):
        for src in json.loads(row["discovery_sources_json"] or "[]"):
            source_counts[src] += 1
    for src, n in source_counts.most_common():
        print(f"  {src}: {n}")
    print(f"Total papers (deduplicated): {total_papers}")

    n_fulltext = conn.execute("SELECT COUNT(*) c FROM papers WHERE fulltext_status='available'").fetchone()["c"]
    n_screened_relevant = conn.execute("SELECT COUNT(*) c FROM papers WHERE processing_status IN ('screened_relevant','extraction_complete')").fetchone()["c"]
    n_with_attempts = conn.execute("SELECT COUNT(DISTINCT paper_id) c FROM engineering_attempts").fetchone()["c"]
    print(f"\nPapers with PMC full text: {n_fulltext}")
    print(f"Papers screened relevant: {n_screened_relevant}")
    print(f"Papers containing at least one real experimental attempt: {n_with_attempts}")

    total_attempts = conn.execute("SELECT COUNT(*) c FROM engineering_attempts").fetchone()["c"]
    print(f"\nTotal engineering_attempts rows: {total_attempts}")
    for row in conn.execute("SELECT outcome, COUNT(*) c FROM engineering_attempts GROUP BY outcome ORDER BY c DESC"):
        print(f"  {row['outcome']}: {row['c']}")

    n_species = conn.execute("SELECT COUNT(DISTINCT species) c FROM engineering_attempts WHERE species != ''").fetchone()["c"]
    n_strains = conn.execute("SELECT COUNT(DISTINCT species || '|' || strain) c FROM engineering_attempts WHERE strain != ''").fetchone()["c"]
    n_explicit_wt = conn.execute("SELECT COUNT(*) c FROM engineering_attempts WHERE wild_type_status='explicit_wild_type'").fetchone()["c"]
    print(f"\nUnique species: {n_species}")
    print(f"Unique species+strain combinations: {n_strains}")
    print(f"Explicit wild-type attempts: {n_explicit_wt}")

    n_multi_strain = conn.execute(
        "SELECT COUNT(*) c FROM (SELECT paper_id FROM engineering_attempts WHERE strain != '' "
        "GROUP BY paper_id HAVING COUNT(DISTINCT strain) > 1)"
    ).fetchone()["c"]
    print(f"Multi-strain papers (>1 distinct strain in one paper): {n_multi_strain}")

    print(f"\nTechniques represented:")
    for row in conn.execute(
        "SELECT technique_normalized, COUNT(*) c FROM engineering_attempts WHERE technique_normalized != '' "
        "GROUP BY technique_normalized ORDER BY c DESC"
    ):
        print(f"  {row['technique_normalized']}: {row['c']}")

    n_needs_review = conn.execute("SELECT COUNT(*) c FROM engineering_attempts WHERE needs_review=1").fetchone()["c"]
    print(f"\nAttempts flagged needs_review (evidence not verified verbatim): {n_needs_review}")
    print("=" * 72)


def run() -> None:
    conn = get_connection()
    try:
        print(f"Writing reports to {REPORTS_DIR}/")
        generate_reports(conn)
        print()
        print_summary(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    run()
