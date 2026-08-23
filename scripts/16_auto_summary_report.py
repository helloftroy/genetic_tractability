# -*- coding: utf-8 -*-
"""Summary for the automated (qwen + keyword-lexicon) extraction pass,
plus a comparison against the manual pass (script 07) wherever both
pipelines happened to process the same paper -- the closest thing this
project has to an automated-vs-hand-curated accuracy check."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, read_csv_dicts


def main() -> None:
    triage = read_csv_dicts(DATA_DIR / "abstract_triage.csv")
    spans_index = read_csv_dicts(DATA_DIR / "keyword_spans_index.csv")
    auto_obs = read_csv_dicts(DATA_DIR / "manipulation_observations_auto.csv")
    manual_obs = read_csv_dicts(DATA_DIR / "manipulation_observations.csv")

    triage_counts = Counter(r["decision"] for r in triage)
    n_with_signal = sum(1 for r in spans_index if r["has_signal"] == "True")

    outcome_counts = Counter(o["outcome"] for o in auto_obs)
    wt_counts = Counter(o["wild_type_status"] for o in auto_obs)
    unverified = sum(1 for o in auto_obs if "evidence_unverified" in o.get("qc_flags", ""))
    auto_papers = set(o["paper_id"] for o in auto_obs)

    print("=" * 72)
    print("AUTOMATED EXTRACTION PIPELINE (qwen triage + keyword spans + qwen structuring)")
    print("=" * 72)
    print(f"Papers triaged: {len(triage)}  -- yes={triage_counts.get('yes',0)} "
          f"no={triage_counts.get('no',0)} maybe={triage_counts.get('maybe',0)}")
    print(f"Keyword-span packets built: {len(spans_index)}  (with real manipulation+outcome/strain signal: {n_with_signal})")
    print(f"Papers with at least one extracted record: {len(auto_papers)}")
    print(f"Total automated observations: {len(auto_obs)}")
    print(f"  evidence_text verified verbatim: {len(auto_obs) - unverified}/{len(auto_obs)}"
          f" ({unverified} flagged evidence_unverified, kept not dropped)")
    print()
    print("Outcome distribution:", dict(outcome_counts))
    print("Wild-type status distribution:", dict(wt_counts))

    overlap = auto_papers & set(o["paper_id"] for o in manual_obs)
    print()
    print(f"Papers present in BOTH the manual (step-1) and automated (step-3) passes: {len(overlap)}")
    if overlap:
        print("(Spot-check these paper_ids directly -- same paper, two independent extraction methods.)")
        for pid in list(overlap)[:10]:
            print(f"  {pid}")

    print()
    print("10 representative automated records:")
    for o in auto_obs[:10]:
        print(f"\n[{o['observation_id']}] {o['organism_name']} — {o['strain_name']}")
        print(f"  Category: {o['manipulation_category']} | Outcome: {o['outcome']} | WT: {o['wild_type_status']} | qc_flags: {o['qc_flags'] or '(none)'}")
        print(f"  Evidence: \"{o['evidence_text'][:200]}\"")


if __name__ == "__main__":
    main()
