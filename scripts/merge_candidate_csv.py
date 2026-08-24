# -*- coding: utf-8 -*-
"""One-off utility for reconciling two independently-grown copies of
candidate_papers.csv / review_seeds.csv -- e.g. a `git pull` that would
otherwise overwrite a cluster's own uncommitted discovery run with a Mac's
pushed version, or vice versa. Reuses CandidateStore's existing DOI/PMID/
title dedup (candidate_store.py) so the two runs' results are unioned, not
one silently discarded in favor of the other.

Usage (run from scripts/, after backing up the file(s) you're about to
`git checkout --`/pull over):
    python3 merge_candidate_csv.py <other_candidate_papers.csv> [<other_review_seeds.csv>]

Merges INTO whatever candidate_papers.csv/review_seeds.csv are currently
on disk (the freshly-pulled ones) and overwrites them in place with the
union.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from candidate_store import CandidateStore
from common import DATA_DIR, read_csv_dicts, write_csv_dicts


def as_bool(value: str) -> bool:
    return str(value).strip().lower() == "true"


def merge_candidate_papers(other_path: Path) -> int:
    store = CandidateStore()
    other_rows = read_csv_dicts(other_path)
    n_before = len(store.all_rows())

    for row in other_rows:
        # Split a possibly-compound discovery_route ("a|b") into individual
        # tokens -- add() unions a single incoming token against whatever
        # the existing row already has; feeding it a whole compound string
        # unsplit would add that string as one odd token instead of
        # properly unioning each route it represents.
        routes = [r.strip() for r in (row.get("discovery_route") or "").split("|") if r.strip()] or [""]
        for route in routes:
            store.add(
                title=row.get("title", ""),
                doi=row.get("doi", ""),
                pmid=row.get("pmid", ""),
                pmcid=row.get("pmcid", ""),
                year=row.get("year", ""),
                journal=row.get("journal", ""),
                authors=row.get("authors", ""),
                source_database=row.get("source_database", "europe_pmc") or "europe_pmc",
                discovery_route=route,
                discovery_query=row.get("discovery_query", ""),
                review_seed_doi=row.get("review_seed_doi", ""),
                is_review=as_bool(row.get("is_review", "")),
                full_text_available=as_bool(row.get("full_text_available", "")),
                processing_status=row.get("processing_status", "discovered") or "discovered",
                notes=row.get("notes", ""),
            )

    store.save()
    n_after = len(store.all_rows())
    print(f"candidate_papers.csv: {n_before} rows before merge, "
          f"{len(other_rows)} rows read from {other_path}, {n_after} rows after merge "
          f"({n_after - n_before} genuinely new)")
    return n_after


def merge_review_seeds(other_path: Path) -> int:
    fieldnames = ["paper_id", "title", "doi", "pmid", "year", "journal", "topic_area", "discovery_query", "notes"]
    current = read_csv_dicts(DATA_DIR / "review_seeds.csv")
    seen = {r["paper_id"] for r in current}
    n_before = len(current)

    for row in read_csv_dicts(other_path):
        if row["paper_id"] not in seen:
            seen.add(row["paper_id"])
            current.append(row)

    write_csv_dicts(DATA_DIR / "review_seeds.csv", current, fieldnames)
    print(f"review_seeds.csv: {n_before} rows before merge, {len(current)} rows after merge "
          f"({len(current) - n_before} genuinely new)")
    return len(current)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 merge_candidate_csv.py <other_candidate_papers.csv> [<other_review_seeds.csv>]",
              file=sys.stderr)
        sys.exit(2)

    other_candidates = Path(sys.argv[1])
    if not other_candidates.exists():
        print(f"File not found: {other_candidates}", file=sys.stderr)
        sys.exit(2)
    merge_candidate_papers(other_candidates)

    if len(sys.argv) > 2:
        other_reviews = Path(sys.argv[2])
        if not other_reviews.exists():
            print(f"File not found: {other_reviews}", file=sys.stderr)
            sys.exit(2)
        merge_review_seeds(other_reviews)


if __name__ == "__main__":
    main()
