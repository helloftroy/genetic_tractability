# -*- coding: utf-8 -*-
"""Prints a full pipeline status report: which script/sbatch produces each
file, what each number actually means, a real yes/no/maybe breakdown from
triage, a genome-match freshness check, and a concrete "what to submit
next" recommendation. Appended to the end of every cluster/*.sbatch script.

Rewritten after real confusion using the old terser version: it wasn't
clear which script produced which file, the triage yes/no/maybe split
wasn't shown at all (only a bare row count), and "keyword-span packets
with real signal" was mistaken for a genome-match count (it's a pre-LLM
keyword heuristic, has nothing to do with genome matching -- that's
stage 5, a separate job). This version labels every section with its
producing script and submit command, and states plainly what each count
does and doesn't mean.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, read_csv_dicts

GENOME_MATCH_STATUSES = [
    "exact_strain_match", "multiple_possible_matches", "species_only_match",
    "no_genome_found", "not_checked",
]


def human_size(n: float) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def mtime_str(path: Path) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime))


def file_line(path: Path, rows: int) -> str:
    size = human_size(path.stat().st_size)
    return f"    {path.name:<38} {rows:>8} rows  {size:>8}  modified {mtime_str(path)}"


def main() -> None:
    print("=" * 72)
    print(f"GENETIC TRACTABILITY PIPELINE STATUS -- {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print("=" * 72)

    next_steps = []

    # ---------------- Stage 1: discovery ----------------
    print()
    print("STAGE 1 -- DISCOVERY  (submit: run_discovery.sbatch | scripts 01-04, 12, 11)")
    print("  Finds and catalogs candidate papers. No LLM, needs internet.")
    papers_path = DATA_DIR / "candidate_papers.csv"
    papers = read_csv_dicts(papers_path)
    n_candidates_total = len(papers)
    n_reviews = sum(1 for p in papers if p.get("is_review") == "True")
    n_candidates = n_candidates_total - n_reviews
    if papers_path.exists():
        print(file_line(papers_path, n_candidates_total))
        print(f"      -> {n_candidates} primary papers, {n_reviews} reviews (reviews are discovery seeds, "
              f"not evidence)")
    else:
        print("    candidate_papers.csv                   (not yet created -- run_discovery.sbatch hasn't run)")

    # ---------------- Stage 2: triage ----------------
    print()
    print("STAGE 2 -- TRIAGE  (submit: run_extraction.sbatch | script 13, needs LLM + cached abstracts)")
    print('  Question asked per paper: "does this actually describe a real genetic-manipulation attempt?"')
    triage_path = DATA_DIR / "abstract_triage.csv"
    triage = read_csv_dicts(triage_path)
    n_triaged = len(triage)
    n_yes = sum(1 for t in triage if t.get("decision") == "yes")
    n_no = sum(1 for t in triage if t.get("decision") == "no")
    n_maybe_rows = [t for t in triage if t.get("decision") == "maybe"]
    n_maybe = len(n_maybe_rows)
    n_forced_maybe = sum(1 for t in n_maybe_rows if t.get("abstract_available") == "False")
    n_triaged_yes_maybe = n_yes + n_maybe
    if triage_path.exists():
        print(file_line(triage_path, n_triaged))
        print(f"      -> yes:   {n_yes:>7}  (likely relevant -- proceeds to keyword-span tagging)")
        print(f"      -> no:    {n_no:>7}  (likely NOT relevant -- stops here, not evidence)")
        print(f"      -> maybe: {n_maybe:>7}  (ambiguous content OR abstract lookup failed -- also proceeds)")
        print(f"                   of which {n_forced_maybe} are \"maybe\" only because the abstract lookup "
              f"failed (not genuine ambiguity) -- see script 20 / run_prefetch.sbatch's healing step")
        untriaged = max(0, n_candidates - n_triaged)
        print(f"      backlog: {untriaged} primary papers not yet triaged")
    else:
        print("    abstract_triage.csv                    (not yet created -- run_extraction.sbatch hasn't triaged anything)")

    # ---------------- Stage 3: keyword-span tagging ----------------
    print()
    print("STAGE 3 -- KEYWORD-SPAN TAGGING  (submit: run_extraction.sbatch | script 14, NO LLM, deterministic)")
    print("  Tags sentences by keyword category (manipulation/success/failure/strain/etc) -- a fast")
    print("  pre-filter, not a real read of the paper. NOT a genome-match count, NOT a confirmed result.")
    spans_path = DATA_DIR / "keyword_spans_index.csv"
    spans_index = read_csv_dicts(spans_path)
    n_spans = len(spans_index)
    n_spans_with_signal = sum(1 for r in spans_index if r.get("has_signal") == "True")
    n_spans_no_signal = n_spans - n_spans_with_signal
    if spans_path.exists():
        print(file_line(spans_path, n_spans))
        print(f"      -> with real signal:    {n_spans_with_signal:>7}  (has manipulation + outcome/strain "
              f"language -- ready for LLM extraction)")
        print(f"      -> without real signal: {n_spans_no_signal:>7}  (keyword-tagged but nothing looked "
              f"like a real attempt -- dead end, not sent to the LLM)")
        span_backlog = max(0, n_triaged_yes_maybe - n_spans)
        print(f"      backlog: {span_backlog} triaged yes/maybe papers still waiting for this stage")
    else:
        print("    keyword_spans_index.csv                (not yet created)")

    # ---------------- Stage 4: LLM structured extraction ----------------
    print()
    print("STAGE 4 -- LLM STRUCTURED EXTRACTION  (submit: run_extraction.sbatch | script 15, the actual qwen calls)")
    print("  Reads ONLY the keyword-tagged sentences (never the raw paper) and extracts one record per")
    print("  organism/strain x technique x outcome. This is the real evidence-level output.")
    obs_path = DATA_DIR / "manipulation_observations_auto.csv"
    obs = read_csv_dicts(obs_path)
    n_obs = len(obs)
    n_obs_papers = len(set(r["paper_id"] for r in obs))
    if obs_path.exists():
        print(file_line(obs_path, n_obs))
        print(f"      -> {n_obs} observation records from {n_obs_papers} distinct papers "
              f"(one paper can yield multiple records: different strains/techniques/outcomes)")
        extraction_backlog = max(0, n_spans_with_signal - n_obs_papers)
        print(f"      backlog: {extraction_backlog} papers have real signal but haven't been LLM-extracted yet")
    else:
        print("    manipulation_observations_auto.csv     (not yet created)")
        extraction_backlog = 0

    # One run_extraction.sbatch submission covers stages 2+3+4 together (scripts
    # 13/14/15 all receive the SAME BATCH_SIZE, each independently capping its own
    # stage at it) -- a single big-enough BATCH_SIZE clears all three backlogs in
    # one job, not three separate submissions.
    combined_backlog = max(untriaged, span_backlog, extraction_backlog)
    if combined_backlog > 0:
        parts = []
        if untriaged > 0:
            parts.append(f"{untriaged} untriaged")
        if span_backlog > 0:
            parts.append(f"{span_backlog} awaiting keyword-spans")
        if extraction_backlog > 0:
            parts.append(f"{extraction_backlog} awaiting LLM extraction")
        if untriaged > 0:
            next_steps.append(
                f"run_prefetch.sbatch (BATCH_SIZE={combined_backlog}) THEN run_extraction.sbatch "
                f"(same BATCH_SIZE) -- covers all three stage backlogs in one pair of jobs "
                f"({', '.join(parts)})")
        else:
            next_steps.append(
                f"run_extraction.sbatch (BATCH_SIZE={combined_backlog}) -- covers all three stage backlogs "
                f"in one job ({', '.join(parts)}); no prefetch needed, nothing untriaged")

    # ---------------- Stage 5: genome matching ----------------
    print()
    print("STAGE 5 -- GENOME MATCHING  (submit: run_genome_matching.sbatch | script 09, SEPARATE job, needs internet)")
    print("  Resolves each observation's organism/strain against NCBI assembly. Does NOT run automatically")
    print("  as part of run_extraction.sbatch -- must be submitted on its own, and re-run whenever")
    print("  manipulation_observations_auto.csv has grown since the last genome-matching run.")
    gm_path = DATA_DIR / "genome_matches_auto.csv"
    gm_rows = read_csv_dicts(gm_path)
    n_gm = len(gm_rows)
    if gm_path.exists():
        print(file_line(gm_path, n_gm))
        if obs_path.exists() and gm_path.stat().st_mtime < obs_path.stat().st_mtime:
            print(f"      *** STALE: manipulation_observations_auto.csv ({n_obs} rows, modified "
                  f"{mtime_str(obs_path)}) is newer than this file ({n_gm} rows, modified {mtime_str(gm_path)}).")
            print(f"      *** These counts only cover an earlier, smaller set of observations. "
                  f"Re-run run_genome_matching.sbatch. ***")
            next_steps.append("run_genome_matching.sbatch to refresh stale genome matches")
        status_counts = {s: 0 for s in GENOME_MATCH_STATUSES}
        for r in gm_rows:
            status_counts[r.get("genome_match_status", "not_checked")] = status_counts.get(
                r.get("genome_match_status", "not_checked"), 0) + 1
        print(f"      -> exact_strain_match:        {status_counts.get('exact_strain_match', 0):>7}  "
              f"(exact experimental strain resolved to a real genome accession)")
        print(f"      -> multiple_possible_matches: {status_counts.get('multiple_possible_matches', 0):>7}  "
              f"(exact strain matched >1 assembly -- needs manual disambiguation)")
        print(f"      -> species_only_match:        {status_counts.get('species_only_match', 0):>7}  "
              f"(a genome exists for the species, but NOT confirmed for this exact strain)")
        print(f"      -> no_genome_found:           {status_counts.get('no_genome_found', 0):>7}  "
              f"(no matching assembly found at all)")
    else:
        print("    genome_matches_auto.csv                (not yet created)")
        if n_obs > 0:
            next_steps.append("run_genome_matching.sbatch (no genome matches computed yet)")

    # ---------------- Manual-pass reference files (not part of the automated cluster pipeline) ----------------
    manual_files = ["manipulation_observations.csv", "genome_matches.csv", "manual_review.csv"]
    if any((DATA_DIR / f).exists() for f in manual_files):
        print()
        print("REFERENCE: hand-curated manual pass (not touched by any sbatch script -- ground-truth")
        print("comparison set, static since it was built)")
        for name in manual_files:
            p = DATA_DIR / name
            if p.exists():
                print(file_line(p, len(read_csv_dicts(p))))

    print()
    print("=" * 72)
    print("WHAT TO SUBMIT NEXT")
    print("=" * 72)
    if next_steps:
        for step in next_steps:
            print(f"  -> {step}")
    else:
        print("  Nothing obviously pending -- all stages are caught up with each other.")
    print("=" * 72)


if __name__ == "__main__":
    main()
