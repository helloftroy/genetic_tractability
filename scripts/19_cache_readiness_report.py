# -*- coding: utf-8 -*-
"""Answers "how much of the pending backlog is already fetched (cached)
and ready to process without touching the network" -- distinct from the
PIPELINE BACKLOG section of 17_data_state_report.py, which shows how far
each paper has gotten through *processing*, not whether its abstract/full
text is actually sitting in data/cache/ already.

Does zero network calls -- reconstructs the same URLs
epmc_lookup_record()/epmc_fulltext_xml() would use from each paper's
already-known doi/pmid/title/pmcid, and just checks whether that URL's
cache file exists on disk (a filesystem stat, not a fetch).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, epmc_fulltext_url, epmc_lookup_url, is_cached, read_csv_dicts


def main() -> None:
    papers = {p["paper_id"]: p for p in read_csv_dicts(DATA_DIR / "candidate_papers.csv") if p.get("is_review") != "True"}
    triage = read_csv_dicts(DATA_DIR / "abstract_triage.csv")
    triaged_ids = {t["paper_id"] for t in triage}
    triaged_yes_maybe_ids = {t["paper_id"] for t in triage if t.get("decision") in ("yes", "maybe")}

    spans_dir = DATA_DIR / "keyword_spans"
    spanned_ids = {p.stem for p in spans_dir.glob("*.json")} if spans_dir.exists() else set()

    untriaged_ids = set(papers) - triaged_ids
    awaiting_spans_ids = triaged_yes_maybe_ids - spanned_ids

    def abstract_cached(pid: str) -> bool:
        p = papers.get(pid)
        if not p:
            return False
        url = epmc_lookup_url(p.get("doi", ""), p.get("pmid", ""), p.get("title", ""))
        return is_cached(url, "json")

    def fulltext_cached(pid: str) -> bool:
        p = papers.get(pid)
        if not p or not p.get("pmcid"):
            return False
        return is_cached(epmc_fulltext_url(p["pmcid"]), "text")

    print("=" * 72)
    print("CACHE READINESS (no network calls -- filesystem check only)")
    print("=" * 72)

    n = len(untriaged_ids)
    n_ready = sum(1 for pid in untriaged_ids if abstract_cached(pid))
    print(f"Untriaged candidates:                    {n:>8}")
    print(f"  -> already have a cached abstract:      {n_ready:>8}  "
          f"(ready for script 13 with zero network)")
    print(f"  -> NOT cached, need run_prefetch.sbatch: {n - n_ready:>8}")
    print()

    n2 = len(awaiting_spans_ids)
    n2_fulltext = sum(1 for pid in awaiting_spans_ids if fulltext_cached(pid))
    n2_abstract_only = sum(
        1 for pid in awaiting_spans_ids
        if not fulltext_cached(pid) and abstract_cached(pid)
    )
    n2_neither = n2 - n2_fulltext - n2_abstract_only
    print(f"Triaged yes/maybe, awaiting keyword-span extraction: {n2:>8}")
    print(f"  -> full text already cached:            {n2_fulltext:>8}  "
          f"(ready for script 14 with zero network, best case)")
    print(f"  -> only abstract cached (no full text):  {n2_abstract_only:>8}  "
          f"(script 14 will fall back to abstract-only spans)")
    print(f"  -> NOT cached at all, need prefetch:      {n2_neither:>8}")
    print("=" * 72)
    print("Note: 'ready to extract' in the everyday sense (script 15, the LLM")
    print("structuring step) doesn't need any network at all -- it only reads")
    print("local keyword_spans/*.json packets. See 17_data_state_report.py's")
    print("PIPELINE BACKLOG section for that count (\"have signal but not yet")
    print("extracted\").")


if __name__ == "__main__":
    main()
