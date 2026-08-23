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

    def priority(p: dict) -> tuple:
        route = p.get("discovery_route", "")
        return (
            0 if p["paper_id"] in has_organism_guess else 1,
            0 if "negative_keyword" in route else 1,
            0 if "broad_keyword" in route else 1,
            0 if "review_reference" in route else 1,
        )

    candidates.sort(key=priority)
    return candidates[:limit]
