# -*- coding: utf-8 -*-
"""Joins the three separate automated-pipeline outputs into one flat CSV for
human spot-checking: manipulation_observations_auto.csv (strain/technique/
outcome/quote, keyed by observation_id) + genome_matches_auto.csv (genome
confirmation, same key) + candidate_papers.csv (title/DOI/PMID, keyed by
paper_id). No column in any single source file lets a reviewer go from "is
this strain real and was the outcome success or failure" straight to "which
paper, and what's the DOI" without opening a second or third file -- this
exists purely to remove that friction for a manual accuracy pass.

Genome match freshness follows 17_data_state_report.py's own check: if
genome_matches_auto.csv predates manipulation_observations_auto.csv, some
newer observations won't have a match yet (empty genome_* columns here,
not an error) -- rerun run_genome_matching.sbatch first if you want every
row's genome confidence filled in before reviewing.

Usage:
  python3 18_export_review_csv.py                          # everything
  python3 18_export_review_csv.py --status exact_strain_match
  python3 18_export_review_csv.py --sample 200              # random spot-check subset
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, read_csv_dicts, write_csv_dicts

FIELDNAMES = [
    "observation_id", "paper_id", "title", "doi", "pmid", "pmcid", "year", "journal",
    "organism_name", "strain_name", "wild_type_status", "manipulation_category",
    "manipulation_detail", "outcome", "failure_reason", "evidence_text", "section_name",
    "qc_flags", "genome_match_status", "gcf_accession", "gca_accession", "ncbi_taxid",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--status", default=None,
                         help="only rows with this genome_match_status (e.g. exact_strain_match)")
    parser.add_argument("--outcome", default=None, help="only rows with this outcome (success/partial/failure/unclear)")
    parser.add_argument("--sample", type=int, default=None, help="random subset of this size, for spot-checking")
    parser.add_argument("--seed", type=int, default=0, help="random seed for --sample (default 0, reproducible)")
    args = parser.parse_args()

    obs = read_csv_dicts(DATA_DIR / "manipulation_observations_auto.csv")
    genome_by_obs = {r["observation_id"]: r for r in read_csv_dicts(DATA_DIR / "genome_matches_auto.csv")}
    papers_by_id = {r["paper_id"]: r for r in read_csv_dicts(DATA_DIR / "candidate_papers.csv")}

    rows = []
    n_missing_paper = n_missing_genome = 0
    for o in obs:
        paper = papers_by_id.get(o["paper_id"])
        if paper is None:
            n_missing_paper += 1
        genome = genome_by_obs.get(o["observation_id"])
        if genome is None:
            n_missing_genome += 1
        rows.append({
            "observation_id": o["observation_id"],
            "paper_id": o["paper_id"],
            "title": paper.get("title", "") if paper else "",
            "doi": paper.get("doi", "") if paper else "",
            "pmid": paper.get("pmid", "") if paper else "",
            "pmcid": paper.get("pmcid", "") if paper else "",
            "year": paper.get("year", "") if paper else "",
            "journal": paper.get("journal", "") if paper else "",
            "organism_name": o.get("organism_name", ""),
            "strain_name": o.get("strain_name", ""),
            "wild_type_status": o.get("wild_type_status", ""),
            "manipulation_category": o.get("manipulation_category", ""),
            "manipulation_detail": o.get("manipulation_detail", ""),
            "outcome": o.get("outcome", ""),
            "failure_reason": o.get("failure_reason", ""),
            "evidence_text": o.get("evidence_text", ""),
            "section_name": o.get("section_name", ""),
            "qc_flags": o.get("qc_flags", ""),
            "genome_match_status": genome.get("genome_match_status", "") if genome else "not_yet_matched",
            "gcf_accession": genome.get("gcf_accession", "") if genome else "",
            "gca_accession": genome.get("gca_accession", "") if genome else "",
            "ncbi_taxid": genome.get("ncbi_taxid", "") if genome else "",
        })

    if args.status:
        rows = [r for r in rows if r["genome_match_status"] == args.status]
    if args.outcome:
        rows = [r for r in rows if r["outcome"] == args.outcome]

    out_name = "review_export.csv"
    if args.sample:
        random.Random(args.seed).shuffle(rows)
        rows = rows[:args.sample]
        out_name = f"review_export_sample{args.sample}.csv"

    out_path = DATA_DIR / out_name
    write_csv_dicts(out_path, rows, FIELDNAMES)

    print(f"Wrote {len(rows)} rows to {out_path}")
    if n_missing_paper:
        print(f"  WARNING: {n_missing_paper} observations reference a paper_id not found in "
              f"candidate_papers.csv (title/doi left blank for those)")
    if n_missing_genome and not args.status:
        print(f"  {n_missing_genome} observations have no genome match yet (genome_match_status="
              f"not_yet_matched) -- run_genome_matching.sbatch hasn't covered them, not an error")


if __name__ == "__main__":
    main()
