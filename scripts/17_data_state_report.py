# -*- coding: utf-8 -*-
"""Prints a snapshot of every pipeline data file's row count, size, and
last-modified time. Appended to the end of every cluster/*.sbatch script
so a completed job's log always shows unambiguous proof it finished and
exactly what state it left the pipeline in -- no need to separately SSH
in and inspect the filesystem to tell "did this actually finish" from
"is this still running/did it die silently".
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR

FILES = [
    "candidate_papers.csv",
    "review_seeds.csv",
    "review_table_extractions.csv",
    "abstract_triage.csv",
    "keyword_spans_index.csv",
    "manipulation_observations.csv",
    "genome_matches.csv",
    "manual_review.csv",
    "manipulation_observations_auto.csv",
    "genome_matches_auto.csv",
]


def human_size(n: float) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def row_count(path: Path) -> int:
    with path.open("rb") as f:
        return sum(1 for _ in f) - 1  # minus header row


def main() -> None:
    print("=" * 72)
    print(f"DATA STATE SNAPSHOT -- {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print("=" * 72)
    for name in FILES:
        path = DATA_DIR / name
        if not path.exists():
            print(f"  {name:<42} (not yet created)")
            continue
        try:
            n = row_count(path)
        except Exception:
            n = -1
        mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime))
        size = human_size(path.stat().st_size)
        print(f"  {name:<42} {n:>7} rows  {size:>8}  modified {mtime}")

    spans_dir = DATA_DIR / "keyword_spans"
    if spans_dir.exists():
        n_spans = sum(1 for _ in spans_dir.glob("*.json"))
        print(f"  {'keyword_spans/ (packet count)':<42} {n_spans:>7} files")
    print("=" * 72)


if __name__ == "__main__":
    main()
