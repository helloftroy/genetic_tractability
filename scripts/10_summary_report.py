# -*- coding: utf-8 -*-
"""Prints the run summary specified in spec section 17, plus ~10
representative observation records for manual quality inspection."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, read_csv_dicts


def main() -> None:
    papers = read_csv_dicts(DATA_DIR / "candidate_papers.csv")
    reviews = read_csv_dicts(DATA_DIR / "review_seeds.csv")
    obs = read_csv_dicts(DATA_DIR / "manipulation_observations.csv")
    genome = read_csv_dicts(DATA_DIR / "genome_matches.csv")
    manual = read_csv_dicts(DATA_DIR / "manual_review.csv")

    n_primary = sum(1 for p in papers if p.get("is_review") != "True")
    n_review = sum(1 for p in papers if p.get("is_review") == "True")

    organisms = set(o["organism_name"] for o in obs)
    strains = set((o["organism_name"], o["strain_name"]) for o in obs)

    cat_counts = Counter()
    for o in obs:
        cat = o["manipulation_category"]
        if cat in ("electroporation",):
            cat_counts["Electroporation"] += 1
        elif cat == "conjugation":
            cat_counts["Conjugation"] += 1
        elif cat in ("natural transformation", "natural competence"):
            cat_counts["Natural transformation"] += 1
        elif "CRISPR" in cat or cat == "genome editing":
            cat_counts["CRISPR"] += 1
        elif cat == "allelic exchange":
            cat_counts["Allelic exchange"] += 1
        else:
            cat_counts["Other"] += 1

    outcome_counts = Counter(o["outcome"] for o in obs)
    wt_counts = Counter(o["wild_type_status"] for o in obs)
    genome_counts = Counter(g["genome_match_status"] for g in genome)
    non_bacterial = sum(1 for o in obs if o["organism_domain"] != "bacteria")

    print("=" * 72)
    print("GENETIC TRACTABILITY DISCOVERY PIPELINE -- RUN SUMMARY")
    print("=" * 72)
    print(f"Total papers discovered:      {len(papers)}")
    print(f"Primary papers:                {n_primary}")
    print(f"Review papers:                 {n_review}")
    print()
    print(f"Unique organisms (name strings): {len(organisms)}")
    print(f"Unique organism+strain pairs:    {len(strains)}")
    print()
    print(f"Manipulation observations:    {len(obs)}")
    print()
    for label in ["Electroporation", "Conjugation", "Natural transformation", "CRISPR", "Allelic exchange", "Other"]:
        print(f"  {label}: {cat_counts.get(label, 0)}")
    print()
    print(f"Success:        {outcome_counts.get('success', 0)}")
    print(f"Failure:        {outcome_counts.get('failure', 0)}")
    print(f"Partial/mixed:  {outcome_counts.get('partial', 0) + outcome_counts.get('mixed', 0)}")
    print(f"Unclear:        {outcome_counts.get('unclear', 0)}")
    print()
    print(f"Wild-type confirmed (yes):  {wt_counts.get('yes', 0)}")
    print(f"Wild-type unclear:          {wt_counts.get('unclear', 0)}")
    print(f"Wild-type excluded (no):    {wt_counts.get('no', 0)}")
    print()
    print(f"Exact strain genome matches:   {genome_counts.get('exact_strain_match', 0)}")
    print(f"  (of which multiple possible): {genome_counts.get('multiple_possible_matches', 0)}")
    print(f"Species-only matches:          {genome_counts.get('species_only_match', 0)}")
    print(f"No genome found:               {genome_counts.get('no_genome_found', 0)}")
    print(f"Not checked:                   {genome_counts.get('not_checked', 0)}")
    print()
    print(f"Non-bacterial organisms retained (observations): {non_bacterial}")
    print(f"Manual-review flagged papers: {len(manual)}")
    print()
    print("Output files:")
    for name in ["candidate_papers.csv", "review_seeds.csv", "manipulation_observations.csv",
                 "genome_matches.csv", "manual_review.csv", "extraction_shortlist.csv",
                 "extraction_shortlist_details.json"]:
        print(f"  {DATA_DIR / name}")
    print()

    print("=" * 72)
    print("10 REPRESENTATIVE RECORDS (mix of success/failure/partial)")
    print("=" * 72)
    by_outcome = {"success": [], "failure": [], "mixed": [], "partial": []}
    for o in obs:
        if o["outcome"] in by_outcome:
            by_outcome[o["outcome"]].append(o)

    sample = []
    sample += by_outcome["failure"][:3]
    sample += by_outcome["success"][:4]
    sample += by_outcome["mixed"][:2]
    sample += by_outcome["partial"][:1]

    paper_titles = {p["paper_id"]: p["title"] for p in papers}
    for o in sample[:10]:
        print(f"\n[{o['observation_id']}] {o['organism_name']} — {o['strain_name']}")
        print(f"  Paper: {paper_titles.get(o['paper_id'], '')[:90]}")
        print(f"  Category: {o['manipulation_category']} | Outcome: {o['outcome']} | WT status: {o['wild_type_status']}")
        print(f"  Evidence: \"{o['evidence_text'][:220]}\"")


if __name__ == "__main__":
    main()
