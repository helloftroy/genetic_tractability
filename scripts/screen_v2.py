# -*- coding: utf-8 -*-
"""Deterministic candidate screening (spec section 14) + full-text passage
extraction (spec section 15) -- the gate between "discovered" and "sent
to the LLM". Nothing here calls an LLM.

For a paper with PMC full text: fetches BioC, tags every Methods/Results/
Supplement passage against technique/failure/success phrases, scores the
paper using spec 14's rubric, and -- for papers that pass the threshold --
writes a compact JSON "chunk packet" (methods/results/supplement passages
plus one paragraph of surrounding context each) to
data/genetic_tractability/chunks_v2/<paper_id>.json. This file, not the
raw paper, is what extract_v2.py's LLM call ever sees (mirrors the v1
pipeline's keyword_spans/*.json design).

For a paper with no PMC full text: scores title+abstract only (a lighter
heuristic -- no Methods/Results distinction available), marks
fulltext_status=unavailable_from_pmc, and is RETAINED (spec section 5: not
discarded) for the future PDF/manual workflow rather than sent to the LLM
in this pass.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from attempt_db import get_connection, now_iso, papers_by_status
from common import DATA_DIR, env_int
from pmc_bioc import fetch_bioc_passages
from technique_vocabulary import (
    ALL_TECHNIQUE_PHRASES, FAILURE_DISCOVERY_PHRASES, GENERIC_DISCOVERY_PHRASES,
    SUCCESS_DISCOVERY_PHRASES,
)

CHUNKS_DIR = DATA_DIR / "chunks_v2"
CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

SCORE_THRESHOLD = env_int("GT2_SCORE_THRESHOLD", 8)

_TITLE_TOOL_PHRASES = [
    "genetic tool", "genetic system", "genetic manipulation", "genetic toolkit",
    "transformation protocol", "electroporation protocol", "conjugation protocol",
]


def _contains_any(text: str, phrases: list[str]) -> list[str]:
    low = text.lower()
    return [p for p in phrases if p.lower() in low]


def score_abstract_only(title: str, abstract: str) -> int:
    """Lighter heuristic for papers with no full text available -- same
    phrase families, no Methods/Results split possible."""
    text = f"{title} {abstract}"
    score = 0
    score += 3 * min(2, len(_contains_any(text, ALL_TECHNIQUE_PHRASES)))
    score += 6 if _contains_any(text, FAILURE_DISCOVERY_PHRASES) else 0
    score += 4 if _contains_any(text, SUCCESS_DISCOVERY_PHRASES) else 0
    score += 3 if _contains_any(title, _TITLE_TOOL_PHRASES) else 0
    score += 2 if _contains_any(text, GENERIC_DISCOVERY_PHRASES) else 0
    return score


def score_and_extract_fulltext(paper_id: str, title: str, passages: list) -> tuple[int, dict]:
    """Spec 14's rubric, computed against real Methods/Results/Supplement
    passages instead of just the abstract. Returns (score, chunk_packet)."""
    score = 0
    if _contains_any(title, _TITLE_TOOL_PHRASES):
        score += 3

    methods_hits, results_hits, supplement_hits = [], [], []
    by_bucket: dict[str, list] = {"METHODS": [], "RESULTS": [], "SUPPLEMENT": []}
    for p in passages:
        if p.section_bucket in by_bucket:
            by_bucket[p.section_bucket].append(p)

    def tag_and_score(bucket_passages: list, technique_pts: int, out_list: list) -> None:
        nonlocal score
        for idx, p in enumerate(bucket_passages):
            tech_hits = _contains_any(p.text, ALL_TECHNIQUE_PHRASES)
            fail_hits = _contains_any(p.text, FAILURE_DISCOVERY_PHRASES)
            success_hits = _contains_any(p.text, SUCCESS_DISCOVERY_PHRASES)
            if not (tech_hits or fail_hits or success_hits):
                continue
            if tech_hits:
                score += technique_pts
            if fail_hits:
                score += 6
            if success_hits:
                score += 4
            chunk_id = f"{p.section_bucket.lower()}_{p.paragraph_index}"
            context_texts = [bucket_passages[i].text for i in (idx - 1, idx, idx + 1)
                              if 0 <= i < len(bucket_passages)]
            out_list.append({
                "chunk_id": chunk_id, "paragraph": p.paragraph_index,
                "matched_technique": tech_hits, "matched_failure": fail_hits, "matched_success": success_hits,
                "text": p.text, "context": " ".join(context_texts),
            })

    tag_and_score(by_bucket["METHODS"], 5, methods_hits)
    tag_and_score(by_bucket["RESULTS"], 5, results_hits)
    tag_and_score(by_bucket["SUPPLEMENT"], 3, supplement_hits)

    # Multi-strain / protocol-development boost (spec sections 30-31).
    full_text_sample = " ".join(p.text for p in passages[:60])
    if re.search(r"\b(\d+|two|three|four|five|six|seven|eight|nine|ten)\s+strains?\b", full_text_sample, re.I):
        score += 3
    if _contains_any(title, ["development of", "optimization of", "efficient transformation"]):
        score += 2

    packet = {
        "paper_id": paper_id, "title": title,
        "methods_chunks": methods_hits, "results_chunks": results_hits, "supplement_chunks": supplement_hits,
    }
    return score, packet


def screen_paper(conn, row) -> None:
    paper_id = row["paper_id"]
    title, abstract = row["title"] or "", row["abstract"] or ""
    pmcid = row["pmcid"] or ""

    if pmcid:
        passages = fetch_bioc_passages(pmcid)
        if passages:
            score, packet = score_and_extract_fulltext(paper_id, title, passages)
            fulltext_status = "available"
            n_chunks = len(packet["methods_chunks"]) + len(packet["results_chunks"]) + len(packet["supplement_chunks"])
            if n_chunks > 0:
                (CHUNKS_DIR / f"{paper_id}.json").write_text(json.dumps(packet, indent=2))
            status = "screened_relevant" if score >= SCORE_THRESHOLD else "screened_irrelevant"
            conn.execute(
                "UPDATE papers SET candidate_score=?, fulltext_status=?, processing_status=?, last_checked_at=? "
                "WHERE paper_id=?",
                (score, fulltext_status, status, now_iso(), paper_id),
            )
            return

    # No PMCID, or PMC has no BioC record for it -- retained per spec section 5.
    score = score_abstract_only(title, abstract)
    status = "screened_relevant" if score >= SCORE_THRESHOLD else "fulltext_unavailable"
    conn.execute(
        "UPDATE papers SET candidate_score=?, fulltext_status=?, processing_status=?, last_checked_at=? WHERE paper_id=?",
        (score, "unavailable_from_pmc", status, now_iso(), paper_id),
    )


def run(max_papers: int | None = None) -> None:
    conn = get_connection()
    try:
        rows = papers_by_status(conn, ["metadata_fetched", "discovered"], limit=max_papers)
        print(f"Screening {len(rows)} papers (threshold={SCORE_THRESHOLD})...")
        n_relevant = n_irrelevant = n_unavailable = 0
        for i, row in enumerate(rows, start=1):
            screen_paper(conn, row)
            if i % 20 == 0:
                conn.commit()
                print(f"  ...{i}/{len(rows)}", flush=True)
        conn.commit()
        counts = conn.execute(
            "SELECT processing_status, COUNT(*) c FROM papers GROUP BY processing_status"
        ).fetchall()
        print("Done. Current status distribution:")
        for c in counts:
            print(f"  {c['processing_status']}: {c['c']}")
    finally:
        conn.close()


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(max_papers=limit)
