# -*- coding: utf-8 -*-
"""Prints a compact pipeline status report: which script produces each file,
a real yes/no/maybe triage breakdown, a genome-match freshness check, and a
concrete "what to submit next" list. Appended to the end of every
cluster/*.sbatch script.

Went through two rewrites. First was too terse: it wasn't clear which
script produced which file, no yes/no/maybe split, and "keyword-span
packets with real signal" got mistaken for a genome-match count (it's a
pre-LLM keyword heuristic -- genome matching is stage 5, a separate job).
Fixed that by spelling everything out in full sentences -- which then
became its own problem (real feedback: "so many words, hard to parse
quickly"). This version keeps every number and the stuck-vs-backlog
distinction from the verbose version, but as short tags instead of
sentences: one line per file, one line per breakdown, one line per
backlog. Run it and read it top to bottom in a few seconds.
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


def mtime_str(path: Path) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime))


def file_line(path: Path, rows: int) -> str:
    return f"  {path.name:<36} {rows:>7} rows   {mtime_str(path)}"


def main() -> None:
    print("=" * 78)
    print(f"GENETIC TRACTABILITY STATUS -- {time.strftime('%Y-%m-%d %H:%M %Z')}")
    print("=" * 78)

    next_steps = []

    # ---------------- Stage 1: discovery ----------------
    print("\n[1] DISCOVERY  (run_discovery.sbatch)")
    papers_path = DATA_DIR / "candidate_papers.csv"
    papers = read_csv_dicts(papers_path)
    n_candidates_total = len(papers)
    n_reviews = sum(1 for p in papers if p.get("is_review") == "True")
    n_candidates = n_candidates_total - n_reviews
    if papers_path.exists():
        print(file_line(papers_path, n_candidates_total))
        print(f"  {n_candidates} primary papers, {n_reviews} review seeds (not evidence)")
    else:
        print("  candidate_papers.csv  -- not created, run_discovery.sbatch hasn't run")

    # ---------------- Stage 2: triage ----------------
    print("\n[2] TRIAGE  (run_extraction.sbatch, script 13, LLM)  -- real attempt described?")
    triage_path = DATA_DIR / "abstract_triage.csv"
    triage = read_csv_dicts(triage_path)
    n_triaged = len(triage)
    n_yes = sum(1 for t in triage if t.get("decision") == "yes")
    n_no = sum(1 for t in triage if t.get("decision") == "no")
    n_maybe_rows = [t for t in triage if t.get("decision") == "maybe"]
    n_maybe = len(n_maybe_rows)
    # Forced-maybe (failed abstract lookup, no content to judge) can't reach
    # script 14 until healed by run_prefetch.sbatch -- counting it as part of
    # the stage-3 backlog was a real bug: made the backlog look unchanged
    # after a real run_extraction.sbatch pass, confirmed live as the
    # explanation for a "the output is the same after I ran it!" report.
    n_forced_maybe = sum(1 for t in n_maybe_rows if t.get("abstract_available") == "False")
    n_genuine_maybe = n_maybe - n_forced_maybe
    n_processable_yes_maybe = n_yes + n_genuine_maybe
    if triage_path.exists():
        print(file_line(triage_path, n_triaged))
        print(f"  yes {n_yes} | no {n_no} | maybe {n_maybe} ({n_genuine_maybe} ambiguous, "
              f"{n_forced_maybe} STUCK: failed abstract lookup -> needs run_prefetch.sbatch healing)")
        untriaged = max(0, n_candidates - n_triaged)
        print(f"  backlog: {untriaged} untriaged")
    else:
        print("  abstract_triage.csv  -- not created, nothing triaged yet")
        untriaged = 0

    # ---------------- Stage 3: keyword-span tagging ----------------
    print("\n[3] KEYWORD SPANS  (run_extraction.sbatch, script 14, no LLM, deterministic)")
    spans_path = DATA_DIR / "keyword_spans_index.csv"
    spans_index = read_csv_dicts(spans_path)
    n_spans = len(spans_index)
    n_spans_with_signal = sum(1 for r in spans_index if r.get("has_signal") == "True")
    n_spans_no_signal = n_spans - n_spans_with_signal
    span_backlog = 0
    if spans_path.exists():
        print(file_line(spans_path, n_spans))
        print(f"  signal {n_spans_with_signal} (-> LLM) | no signal {n_spans_no_signal} (dead end)")
        span_backlog = max(0, n_processable_yes_maybe - n_spans)
        note = f", {n_forced_maybe} forced-maybe stuck separately" if n_forced_maybe else ""
        print(f"  backlog: {span_backlog}{note}")
    else:
        print("  keyword_spans_index.csv  -- not created")

    # ---------------- Stage 4: LLM structured extraction ----------------
    print("\n[4] LLM EXTRACTION  (run_extraction.sbatch, script 15)  -- the real evidence output")
    obs_path = DATA_DIR / "manipulation_observations_auto.csv"
    obs = read_csv_dicts(obs_path)
    n_obs = len(obs)
    n_obs_papers = len(set(r["paper_id"] for r in obs))
    extraction_backlog = 0
    if obs_path.exists():
        print(file_line(obs_path, n_obs))
        print(f"  {n_obs} observations from {n_obs_papers} papers (1 paper -> multiple "
              f"strain/technique/outcome rows)")
        extraction_backlog = max(0, n_spans_with_signal - n_obs_papers)
        print(f"  backlog: {extraction_backlog} papers awaiting extraction")
    else:
        print("  manipulation_observations_auto.csv  -- not created")

    # run_extraction.sbatch's BATCH_SIZE caps stages 2/3/4 (scripts 13/14/15)
    # identically -- one big-enough submission clears all three backlogs.
    combined_backlog = max(untriaged, span_backlog, extraction_backlog)
    if combined_backlog > 0:
        if untriaged > 0:
            next_steps.append(f"run_prefetch.sbatch then run_extraction.sbatch (BATCH_SIZE={combined_backlog}) "
                               f"-- clears untriaged + spans + extraction backlogs together")
        else:
            next_steps.append(f"run_extraction.sbatch (BATCH_SIZE={combined_backlog}) -- clears spans + "
                               f"extraction backlogs; nothing untriaged, no prefetch needed")
    if n_forced_maybe > 0:
        next_steps.append(f"run_prefetch.sbatch -- heals {n_forced_maybe} forced-maybe papers stuck on a "
                           f"failed abstract lookup (run_extraction.sbatch never touches these)")

    # ---------------- Stage 5: genome matching ----------------
    print("\n[5] GENOME MATCHING  (run_genome_matching.sbatch, script 09, SEPARATE job, needs internet)")
    gm_path = DATA_DIR / "genome_matches_auto.csv"
    gm_rows = read_csv_dicts(gm_path)
    n_gm = len(gm_rows)
    if gm_path.exists():
        stale = obs_path.exists() and gm_path.stat().st_mtime < obs_path.stat().st_mtime
        print(file_line(gm_path, n_gm) + ("   *** STALE, rerun ***" if stale else ""))
        if stale:
            print(f"  obs file grew to {n_obs} rows since this ran ({n_gm} rows) -- counts below "
                  f"undercount; run_genome_matching.sbatch")
            next_steps.append("run_genome_matching.sbatch -- refresh stale genome matches")
        status_counts = {s: 0 for s in GENOME_MATCH_STATUSES}
        for r in gm_rows:
            status_counts[r.get("genome_match_status", "not_checked")] = status_counts.get(
                r.get("genome_match_status", "not_checked"), 0) + 1
        print(f"  exact_strain {status_counts.get('exact_strain_match', 0)} | "
              f"multi_match {status_counts.get('multiple_possible_matches', 0)} | "
              f"species_only {status_counts.get('species_only_match', 0)} | "
              f"no_genome {status_counts.get('no_genome_found', 0)}")
    else:
        print("  genome_matches_auto.csv  -- not created")
        if n_obs > 0:
            next_steps.append("run_genome_matching.sbatch -- no genome matches computed yet")

    # ---------------- Manual-pass reference files ----------------
    manual_files = ["manipulation_observations.csv", "genome_matches.csv", "manual_review.csv"]
    if any((DATA_DIR / f).exists() for f in manual_files):
        print("\n[ref] hand-curated manual pass (static, not touched by any sbatch script)")
        for name in manual_files:
            p = DATA_DIR / name
            if p.exists():
                print(file_line(p, len(read_csv_dicts(p))))

    print("\n" + "=" * 78)
    print("NEXT")
    if next_steps:
        for step in next_steps:
            print(f"  -> {step}")
    else:
        print("  Nothing pending -- all stages caught up.")
    print("=" * 78)


if __name__ == "__main__":
    main()
