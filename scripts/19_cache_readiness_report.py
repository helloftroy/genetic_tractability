# -*- coding: utf-8 -*-
"""Answers "how much of the pending backlog is already fetched (cached)
and ready to process without touching the network" -- distinct from
17_data_state_report.py's per-stage backlog numbers, which show how far
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
    triaged_yes_maybe_rows = [t for t in triage if t.get("decision") in ("yes", "maybe")]
    triaged_yes_maybe_ids = {t["paper_id"] for t in triaged_yes_maybe_rows}
    # A "maybe" decision means two very different things that look
    # identical in the decision column: genuine content ambiguity, or the
    # abstract lookup simply failed at triage time (script 13 defaults to
    # "maybe" rather than silently dropping the paper -- per spec: no
    # evidence is not a negative result). Rows of the second kind were
    # never actually read for content and won't have anything cached
    # unless a real prefetch pass succeeds for them later -- the
    # abstract_available column (recorded per-row at triage time) is the
    # ground truth for which is which, not a guess.
    forced_maybe_ids = {t["paper_id"] for t in triaged_yes_maybe_rows if t.get("abstract_available") == "False"}

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

    def is_open_access(pid: str) -> bool:
        p = papers.get(pid)
        return bool(p) and p.get("full_text_available") == "True"

    print("=" * 72)
    print("CACHE READINESS (no network calls -- filesystem check only)")
    print("=" * 72)

    n = len(untriaged_ids)
    n_ready = sum(1 for pid in untriaged_ids if abstract_cached(pid))
    print(f"Untriaged candidates:                       {n:>8}")
    print(f"  -> already have a cached abstract:         {n_ready:>8}  "
          f"(ready for script 13 with zero network)")
    print(f"  -> not cached, needs run_prefetch.sbatch:  {n - n_ready:>8}")
    print()

    n2 = len(awaiting_spans_ids)
    n2_fulltext = sum(1 for pid in awaiting_spans_ids if fulltext_cached(pid))
    n2_abstract_only = sum(
        1 for pid in awaiting_spans_ids
        if not fulltext_cached(pid) and abstract_cached(pid)
    )
    n2_neither = n2 - n2_fulltext - n2_abstract_only
    n2_forced_maybe = len(awaiting_spans_ids & forced_maybe_ids)
    print(f"Triaged yes/maybe, awaiting keyword-span extraction: {n2:>8}")
    print(f"  -> full text already cached:               {n2_fulltext:>8}  "
          f"(ready for script 14 with zero network, best case)")
    print(f"  -> only abstract cached (no full text):     {n2_abstract_only:>8}  "
          f"(script 14 will fall back to abstract-only spans; see the OA breakdown below for why)")
    print(f"  -> not cached at all, needs run_prefetch.sbatch: {n2_neither:>8}")
    if n2_forced_maybe:
        overlap_uncached = len((awaiting_spans_ids & forced_maybe_ids) - {
            pid for pid in awaiting_spans_ids if abstract_cached(pid) or fulltext_cached(pid)
        })
        print(f"     of which {n2_forced_maybe} are \"maybe\" only because the abstract lookup FAILED at "
              f"triage time (never actually read for content) -- {overlap_uncached} of those are still "
              f"uncached now too, and need a real run_prefetch.sbatch pass to become usable at all.")
    print()

    n_oa = sum(1 for pid in awaiting_spans_ids if is_open_access(pid))
    n_not_oa = n2 - n_oa
    print(f"Of those {n2}: {n_oa} are open access (full text is fetchable in principle), "
          f"{n_not_oa} are NOT open access (full text will never be fetched -- paywalled content "
          f"is never touched, by design -- these will permanently stay abstract-only, and that's expected).")
    print("=" * 72)
    print("Note: 'ready to extract' in the everyday sense (script 15, the LLM")
    print("structuring step) doesn't need any network at all -- it only reads")
    print("local keyword_spans/*.json packets. See 17_data_state_report.py's")
    print("STAGE 4 backlog line for that count (\"papers have real signal but")
    print("haven't been LLM-extracted yet\").")


if __name__ == "__main__":
    main()
