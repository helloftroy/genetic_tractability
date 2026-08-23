"""Strip HTML italics tags / unescape entities in title fields for
readability (Europe PMC titles come back with <i>Genus species</i> markup)."""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, read_csv_dicts, write_csv_dicts


def clean(text: str) -> str:
    if not text:
        return text
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    return text


def clean_file(path: Path, fieldnames: list[str]) -> None:
    rows = read_csv_dicts(path)
    if not rows:
        return
    for row in rows:
        if "title" in row:
            row["title"] = clean(row["title"])
    write_csv_dicts(path, rows, fieldnames)


def main() -> None:
    from candidate_store import FIELDNAMES as CAND_FIELDS
    clean_file(DATA_DIR / "candidate_papers.csv", CAND_FIELDS)
    clean_file(DATA_DIR / "review_seeds.csv",
               ["paper_id", "title", "doi", "pmid", "year", "journal", "topic_area", "discovery_query", "notes"])
    clean_file(DATA_DIR / "manual_review.csv",
               ["paper_id", "title", "issue_type", "description", "notes"])
    print("Cleaned title fields in candidate_papers.csv, review_seeds.csv, manual_review.csv")


if __name__ == "__main__":
    main()
