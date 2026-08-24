# -*- coding: utf-8 -*-
"""Shared candidate-paper batch selection, used by both the network-only
prefetch step (12b, runs on the CPU/service node) and the LLM triage step
(13, runs on the GPU node reading the prefetch's warm cache) -- both must
pick the exact same batch, in the exact same order, or prefetch would warm
the cache for papers triage never asks about."""
from __future__ import annotations

from pathlib import Path

from common import DATA_DIR, read_csv_dicts


def select_triage_batch(limit: int, already_triaged: set[str] | None = None) -> list[dict]:
    papers = read_csv_dicts(DATA_DIR / "candidate_papers.csv")
    if already_triaged is None:
        already_triaged = set(r["paper_id"] for r in read_csv_dicts(DATA_DIR / "abstract_triage.csv"))
    table_rows = read_csv_dicts(DATA_DIR / "review_table_extractions.csv")
    has_organism_guess = set(
        r["matched_candidate_paper_id"] for r in table_rows if r.get("organism_guess")
    )

    candidates = [
        p for p in papers
        if p.get("is_review") != "True" and p["paper_id"] not in already_triaged
    ]

    # A single priority sort with table-derived (organism_guess) ranked first
    # was tried initially, but a pure lexicographic sort means the FIRST
    # tuple element dominates completely: since table-derived candidates
    # (~3,300) vastly outnumber negative_keyword ones, they filled the
    # entire batch and negative_keyword never got a real slot -- confirmed
    # live, a 350-candidate batch pulled in 16/17 contributing papers via
    # review_reference and exactly zero via negative_keyword, which visibly
    # skewed the resulting observations toward success/non-wild-type
    # outcomes (spec principle #1: "failure is data" -- a batch that never
    # samples the failure-hunting route can't surface it). Fixed with a
    # quota: reserve a guaranteed share of every batch for negative_keyword
    # candidates regardless of table origin, so failure-search recall
    # can't be crowded out by the (larger, success-biased) table pool.
    negative_pool = [p for p in candidates if "negative_keyword" in p.get("discovery_route", "")]
    table_pool = [
        p for p in candidates
        if p["paper_id"] in has_organism_guess and "negative_keyword" not in p.get("discovery_route", "")
    ]
    other_pool = [
        p for p in candidates
        if p["paper_id"] not in has_organism_guess and "negative_keyword" not in p.get("discovery_route", "")
    ]

    def other_priority(p: dict) -> tuple:
        route = p.get("discovery_route", "")
        return (0 if "broad_keyword" in route else 1, 0 if "review_reference" in route else 1)

    other_pool.sort(key=other_priority)

    negative_quota = max(1, round(limit * 0.35)) if negative_pool else 0
    table_quota = max(1, round(limit * 0.45)) if table_pool else 0

    selected = negative_pool[:negative_quota] + table_pool[:table_quota]
    # Backfill any quota a pool couldn't fill (e.g. negative_pool exhausted)
    # from whichever pool still has candidates, so a small negative_pool
    # never silently shrinks the batch below `limit`.
    remaining = (negative_pool[negative_quota:] + table_pool[table_quota:] + other_pool)
    selected += remaining[: max(0, limit - len(selected))]
    return selected[:limit]
