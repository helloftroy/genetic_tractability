"""Rank non-review candidates and select a manageable subset for first-pass
manual extraction (spec section 16: prioritize recall over exhaustive
processing for the test run; target here is a few dozen papers, not the
full ~3,400-row candidate pool).

Scoring is a simple title-keyword heuristic (organism specificity +
manipulation-method mention + a bonus for the negative_keyword route,
since failure evidence is explicitly high-value per spec principle #1).
This is a triage aid, not a filter -- everything stays in
candidate_papers.csv regardless of score.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, read_csv_dicts

ORGANISM_HINTS = [
    "vibrio", "pseudomonas", "marinobacter", "bacillus", "streptomyces",
    "cyanobacter", "synechococcus", "synechocystis", "rhodobacter",
    "shewanella", "roseobacter", "alteromonas", "flavobacterium",
    "thermus", "thermococcus", "sulfolobus", "haloferax", "methanococcus",
    "archaeon", "archaea", "strain", " sp.", "isolate",
]
MANIPULATION_TERMS = [
    "electroporat", "conjugat", "transform", "crispr", "genome editing",
    "gene editing", "plasmid", "knockout", "knock-out", "knock-in",
    "mutagenesis", "recombineering", "allelic exchange", "transposon",
    "heterologous expression", "competence", "transduction",
    "genetic manipulation", "genetic tool", "genetic system",
]
FAILURE_TERMS = [
    "fail", "unable", "could not", "recalcitrant", "resistant to",
    "unsuccessful", "no transformants", "no colonies", "toxicity", "toxic",
]

SELECT_TOP_N = 60


def score(row: dict) -> int:
    title = (row.get("title") or "").lower()
    s = 0
    if any(term in title for term in ORGANISM_HINTS):
        s += 2
    if any(term in title for term in MANIPULATION_TERMS):
        s += 3
    if any(term in title for term in FAILURE_TERMS):
        s += 2
    if "negative_keyword" in row.get("discovery_route", ""):
        s += 3
    if "organism_specific" in row.get("discovery_route", ""):
        s += 2
    # Penalize titles that look like they're about humans/clinical/agriculture
    # review context rather than a primary manipulation attempt.
    if any(term in title for term in ["review", "perspective", "clinical trial", "meta-analysis"]):
        s -= 3
    return s


def main() -> None:
    rows = read_csv_dicts(DATA_DIR / "candidate_papers.csv")
    primary = [r for r in rows if r.get("is_review") != "True"]
    scored = sorted(primary, key=score, reverse=True)
    selected = scored[:SELECT_TOP_N]

    out_path = DATA_DIR / "extraction_shortlist.csv"
    import csv
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["paper_id", "score", "title", "doi", "pmid", "year", "discovery_route"])
        for r in selected:
            writer.writerow([r["paper_id"], score(r), r["title"], r["doi"], r["pmid"], r["year"], r["discovery_route"]])

    print(f"Total non-review candidates: {len(primary)}")
    print(f"Selected top {len(selected)} for extraction shortlist -> {out_path}")


if __name__ == "__main__":
    main()
