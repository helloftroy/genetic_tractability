"""Sync candidate_papers.csv processing_status with what actually happened
to each paper during the extraction pass (spec section 4's
processing_status field)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from candidate_store import CandidateStore
from common import DATA_DIR, read_csv_dicts


def main() -> None:
    store = CandidateStore()
    obs = read_csv_dicts(DATA_DIR / "manipulation_observations.csv")
    manual = read_csv_dicts(DATA_DIR / "manual_review.csv")

    extracted_paper_ids = set(r["paper_id"] for r in obs)
    manual_paper_ids = set(r["paper_id"] for r in manual)

    for paper_id in extracted_paper_ids:
        store.set_status(paper_id, "extracted")
    for paper_id in manual_paper_ids:
        if paper_id not in extracted_paper_ids:
            store.set_status(paper_id, "manual_review_required")

    for row in store.all_rows():
        if row.get("is_review") == "True" and row["processing_status"] == "review_seed":
            continue  # reviews stay as review_seed

    store.save()
    print(f"Marked {len(extracted_paper_ids)} papers as extracted")
    print(f"Marked {len(manual_paper_ids - extracted_paper_ids)} papers as manual_review_required")


if __name__ == "__main__":
    main()
