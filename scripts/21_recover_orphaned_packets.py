# -*- coding: utf-8 -*-
"""Recovery utility: rebuilds keyword_spans_index.csv entries for any
keyword_spans/*.json packet files that exist on disk but are missing from
the index -- exactly what happens when a run_extraction.sbatch job is
killed (e.g. hitting --time) mid-way through script 14, since each packet
file is written durably per-paper but the index was previously only
written once at the very end (fixed going forward in
14_extract_keyword_spans.py, but this recovers anything orphaned by a run
that happened before that fix, or by any future hard-kill mid-checkpoint).

No network calls -- every packet already contains everything needed to
rebuild its index row (category counts, signal flag, etc). Safe to run
any time; already-indexed packets are skipped.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, locked_merge_write_csv, read_csv_dicts

SPANS_DIR = DATA_DIR / "keyword_spans"
INDEX_FIELDNAMES = [
    "paper_id", "text_source", "n_sentences_total", "n_tagged_sentences",
    "n_manipulation", "n_success", "n_failure", "n_wild_type", "n_not_wild_type",
    "regex_accessions", "regex_strains", "has_signal",
]


def index_row_from_packet(packet: dict) -> dict:
    cat_counts = {cat: len(v) for cat, v in packet.get("spans_by_category", {}).items()}
    has_signal = cat_counts.get("manipulation", 0) > 0 and (
        cat_counts.get("success", 0) > 0 or cat_counts.get("failure", 0) > 0
        or cat_counts.get("strain", 0) > 0
    )
    return {
        "paper_id": packet["paper_id"], "text_source": packet.get("text_source", ""),
        "n_sentences_total": packet.get("n_sentences_total", 0), "n_tagged_sentences": packet.get("n_tagged_sentences", 0),
        "n_manipulation": cat_counts.get("manipulation", 0), "n_success": cat_counts.get("success", 0),
        "n_failure": cat_counts.get("failure", 0), "n_wild_type": cat_counts.get("wild_type", 0),
        "n_not_wild_type": cat_counts.get("not_wild_type", 0),
        "regex_accessions": sum(len(v) for v in packet.get("regex_accessions", {}).values()),
        "regex_strains": len(packet.get("regex_strains", [])),
        "has_signal": has_signal,
    }


def main() -> None:
    if not SPANS_DIR.exists():
        print(f"{SPANS_DIR} does not exist -- nothing to recover.")
        return

    on_disk_ids = {p.stem for p in SPANS_DIR.glob("*.json")}
    indexed_ids = {r["paper_id"] for r in read_csv_dicts(DATA_DIR / "keyword_spans_index.csv")}
    orphaned_ids = on_disk_ids - indexed_ids

    print(f"Packets on disk: {len(on_disk_ids)}; already indexed: {len(indexed_ids)}; "
          f"orphaned (on disk, missing from index): {len(orphaned_ids)}")

    if not orphaned_ids:
        print("Nothing to recover.")
        return

    recovered_rows = []
    n_signal = 0
    for i, paper_id in enumerate(sorted(orphaned_ids), start=1):
        try:
            packet = json.loads((SPANS_DIR / f"{paper_id}.json").read_text())
            row = index_row_from_packet(packet)
            recovered_rows.append(row)
            if row["has_signal"]:
                n_signal += 1
        except Exception as e:
            print(f"  WARNING: could not read/parse {paper_id}.json: {e}")
        if i % 200 == 0:
            print(f"  ...{i}/{len(orphaned_ids)} recovered so far", flush=True)

    locked_merge_write_csv(DATA_DIR / "keyword_spans_index.csv", INDEX_FIELDNAMES, upsert_rows=recovered_rows)
    print(f"Done. Recovered {len(recovered_rows)} orphaned packets into keyword_spans_index.csv "
          f"({n_signal} with real signal, now visible to script 15).")


if __name__ == "__main__":
    main()
