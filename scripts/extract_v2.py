# -*- coding: utf-8 -*-
"""LLM extraction over scored passages (spec sections 16-30) -- the unit
extracted is paper x organism/strain x technique x materially distinct
attempt, NOT one row per paper (spec 17-18: a strain tried three
electroporation conditions with two failures and one eventual success is
THREE rows, not one collapsed "success").

Reads ONLY chunks_v2/<paper_id>.json (screen_v2.py's output) -- never the
raw paper -- same "keep the LLM's input short and pre-filtered" design as
the v1 pipeline's script 15. Every attempt's evidence_method/evidence_result
is verified as a real verbatim substring of a provided chunk before being
trusted (mirrors v1's evidence verification); unverified attempts are kept
(spec: never silently drop) but flagged needs_review.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm_client
from attempt_db import get_connection, insert_attempt, now_iso, papers_by_status
from common import DATA_DIR, env_int
from technique_vocabulary import FAILURE_REASON_VALUES, OUTCOME_VALUES, WILD_TYPE_STATUS_VALUES

CHUNKS_DIR = DATA_DIR / "chunks_v2"
MAX_CONSECUTIVE_LLM_FAILURES = 8
# This prompt is longer (multiple chunks, ~3-4k tokens) than the v1 pipeline's
# abstract-only prompts, and Mac/Ollama CPU inference for it routinely exceeds
# llm_client.chat()'s 120s default -- confirmed live (all 3 retries timed out
# at exactly 120s against a real screened paper). The vLLM/GPU cluster path
# (run_v2_extract.sbatch) is fast enough that this rarely matters there, but
# local testing needs real headroom. Override with GENETIC_TRACTABILITY_LLM_TIMEOUT.
LLM_TIMEOUT = env_int("GENETIC_TRACTABILITY_LLM_TIMEOUT", 300)
# Confirmed live: a real multi-strain paper produced 6 attempts and got cut
# off mid-6th-object at the old max_tokens=2500, which (before the lenient
# parser above existed) silently discarded all 6. Multi-strain and
# protocol-optimization papers (spec 18/30) are exactly the ones that need
# the most output tokens, so this needs real headroom.
MAX_OUTPUT_TOKENS = env_int("GENETIC_TRACTABILITY_LLM_MAX_TOKENS", 6000)

SYSTEM_PROMPT = f"""You extract genetic-engineering ATTEMPTS from pre-selected Methods/Results/Supplement \
passages of a microbiology paper. Read carefully -- this task has several rules that are easy to get wrong.

RULE 1 -- Output ONLY a JSON array (use [] if nothing qualifies). No markdown, no commentary.

RULE 2 -- One array element = ONE organism/strain tried with ONE technique under ONE materially distinct \
set of conditions, with ONE outcome. If the SAME strain and technique was tried under different conditions \
with DIFFERENT results (e.g. standard electroporation failed, but electroporation with methylated DNA \
succeeded), these are SEPARATE elements -- never collapse a failure into a later success. If a paper reports \
multiple strains, or multiple techniques, output separate elements for each.

RULE 3 -- CURRENT-STUDY EXPERIMENTS ONLY. Only extract an attempt if THIS paper's authors performed it \
themselves. Strong indicators this is current-study work: "we transformed", "we attempted", "we tested", \
"cells were transformed", "transformants were selected", "we constructed", "we generated mutants". \
Do NOT extract an attempt from citation-only language describing a DIFFERENT, previously published study: \
"has previously been transformed", "Smith et al. demonstrated", "previous studies showed". A citation \
mentioning a technique is not an attempt performed here.

RULE 4 -- ABSENCE IS NOT FAILURE. Only report outcome="failure" when there is explicit evidence the \
technique was attempted and did not work (e.g. "no transformants were obtained"). If a paper merely says a \
technique was never tried, or that "genetic tools are not available" for a species, that is NOT itself an \
attempt -- do not manufacture a failure record from it. If a paper simply never mentions a technique, do not \
report anything for it.

RULE 5 -- evidence_method and evidence_result MUST be copied character-for-character from the CHUNKS \
provided below (pick the single best chunk's text, or an exact substring of it). NEVER paraphrase, \
summarize, or invent evidence. evidence_method should describe what was attempted (usually from a METHODS \
chunk); evidence_result should describe what happened (usually from a RESULTS chunk). Leave either "" if no \
chunk actually supports it -- do not guess.

RULE 6 -- wild_type_status must be exactly one of: {WILD_TYPE_STATUS_VALUES}. Be conservative: only use \
"explicit_wild_type" if the text explicitly says "wild type"/"wild-type"/"WT" in relation to the tested \
strain. "unmodified_parental_strain" is for a starting isolate with no described prior engineering, but NOT \
explicitly labeled wild type by the authors -- lower confidence than explicit_wild_type. "engineered_background" \
is for a strain that already carries prior genetic modifications before this attempt.

RULE 7 -- outcome must be exactly one of: {OUTCOME_VALUES}. success = the manipulation clearly worked \
(transformants obtained, mutation confirmed, etc). failure = explicitly did not work (no transformants, no \
colonies). partial_success = an intermediate step worked but the full intended result did not (e.g. DNA \
entered cells but plasmid did not replicate). mixed = only use this if multiple conditions/strains are \
summarized together with both success and failure that you genuinely cannot separate into distinct elements \
-- prefer splitting into separate elements per Rule 2 whenever the text allows it. unclear = attempt \
described but outcome not confidently determinable.

RULE 8 -- failure_reason (only if outcome is failure or partial_success and a reason is explicitly stated) \
should be the closest match from: {FAILURE_REASON_VALUES}, or "other" with failure_reason_raw holding the \
actual text if nothing fits.

RULE 9 -- technique_normalized should be a short, standard-agnostic name (e.g. "electroporation", \
"conjugation", "crispr_cas9", "allelic_exchange", "recombineering", "transposon_mutagenesis", \
"natural_transformation", "heterologous_expression"). technique_raw preserves the paper's own wording.

RULE 10 -- Preserve exact strain identifiers exactly as written (e.g. "Vibrio sp. strain X" must NOT be \
guessed into a real species). Do not invent genus/species if the paper only gives a raw name.

Each element's JSON shape:
{{"organism_name_raw": "", "genus": "", "species": "", "strain": "", "wild_type_status": "", \
"technique_raw": "", "technique_normalized": "", "vector_or_construct": "", "plasmid_name": "", \
"delivery_method": "", "selection_method": "", "attempt_conditions_summary": "", "outcome": "", \
"outcome_detail": "", "failure_reason": "", "failure_reason_raw": "", "quantitative_efficiency": "", \
"quantitative_efficiency_unit": "", "evidence_method": "", "evidence_result": ""}}"""

USER_TEMPLATE = """PAPER TITLE: {title}

METHODS CHUNKS (what was attempted):
{methods_block}

RESULTS CHUNKS (what happened):
{results_block}

SUPPLEMENT CHUNKS:
{supplement_block}

Return the JSON array now."""


def normalize_sentence(s: str) -> str:
    return " ".join(s.lower().split())


def _format_chunks(chunks: list[dict]) -> str:
    if not chunks:
        return "(none)"
    lines = []
    for c in chunks:
        lines.append(f"  [{c['chunk_id']}] {c['text']}")
    return "\n".join(lines)


def build_prompt(packet: dict) -> tuple[str, set[str], dict[str, list[str]]]:
    methods_block = _format_chunks(packet.get("methods_chunks", []))
    results_block = _format_chunks(packet.get("results_chunks", []))
    supplement_block = _format_chunks(packet.get("supplement_chunks", []))
    user = USER_TEMPLATE.format(
        title=packet.get("title", ""), methods_block=methods_block,
        results_block=results_block, supplement_block=supplement_block,
    )
    sentence_lookup = set()
    chunk_ids_by_section = {"methods": [], "results": [], "supplement": []}
    for key, section in (("methods_chunks", "methods"), ("results_chunks", "results"), ("supplement_chunks", "supplement")):
        for c in packet.get(key, []):
            sentence_lookup.add(normalize_sentence(c["text"]))
            sentence_lookup.add(normalize_sentence(c.get("context", "")))
            chunk_ids_by_section[section].append(c["chunk_id"])
    return user, sentence_lookup, chunk_ids_by_section


def verify_evidence(evidence_text: str, sentence_lookup: set[str]) -> bool:
    if not evidence_text:
        return True  # an intentionally-empty field (Rule 5's "leave blank rather than guess") isn't a fabrication
    needle = normalize_sentence(evidence_text)
    return any(needle in hay or hay in needle for hay in sentence_lookup if hay)


def make_attempt_id(paper_id: str, index: int) -> str:
    return f"{paper_id}-ATT{index:02d}"


def extract_paper(conn, paper_id: str, packet: dict) -> int:
    user_prompt, sentence_lookup, chunk_ids = build_prompt(packet)
    try:
        raw = llm_client.chat(SYSTEM_PROMPT, user_prompt, max_tokens=MAX_OUTPUT_TOKENS, timeout=LLM_TIMEOUT)
    except llm_client.LLMError:
        raise

    # Always an array per RULE 1; use the lenient parser so a response that
    # got cut off by max_tokens (a real risk for multi-strain papers with
    # many attempts -- spec section 30) still yields every attempt that
    # completed before the cutoff, instead of discarding the whole batch.
    parsed = llm_client.extract_json_array_lenient(raw)
    if not llm_client.strip_think_tags(raw).rstrip().endswith("]"):
        print(f"  [extract] {paper_id}: response looks truncated by max_tokens "
              f"({MAX_OUTPUT_TOKENS}) -- recovered {len(parsed)} complete attempt(s), "
              f"a trailing partial one (if any) was dropped, not fabricated.", flush=True)

    n = 0
    for i, rec in enumerate(parsed, start=1):
        if not isinstance(rec, dict) or not rec.get("organism_name_raw"):
            continue
        evidence_method = str(rec.get("evidence_method", "")).strip()
        evidence_result = str(rec.get("evidence_result", "")).strip()
        verified = verify_evidence(evidence_method, sentence_lookup) and verify_evidence(evidence_result, sentence_lookup)

        outcome = rec.get("outcome") if rec.get("outcome") in OUTCOME_VALUES else "unclear"
        wt = rec.get("wild_type_status") if rec.get("wild_type_status") in WILD_TYPE_STATUS_VALUES else "unclear"

        insert_attempt(
            conn, make_attempt_id(paper_id, i), paper_id,
            organism_name_raw=rec.get("organism_name_raw", ""), genus=rec.get("genus", ""),
            species=rec.get("species", ""), strain=rec.get("strain", ""),
            wild_type_status=wt, technique_raw=rec.get("technique_raw", ""),
            technique_normalized=rec.get("technique_normalized", ""),
            vector_or_construct=rec.get("vector_or_construct", ""), plasmid_name=rec.get("plasmid_name", ""),
            delivery_method=rec.get("delivery_method", ""), selection_method=rec.get("selection_method", ""),
            attempt_conditions_summary=rec.get("attempt_conditions_summary", ""),
            outcome=outcome, outcome_detail=rec.get("outcome_detail", ""),
            failure_reason=rec.get("failure_reason", ""), failure_reason_raw=rec.get("failure_reason_raw", ""),
            quantitative_efficiency=str(rec.get("quantitative_efficiency", "")),
            quantitative_efficiency_unit=rec.get("quantitative_efficiency_unit", ""),
            evidence_method=evidence_method, evidence_result=evidence_result,
            methods_chunk_ids=chunk_ids["methods"], results_chunk_ids=chunk_ids["results"],
            supplement_chunk_ids=chunk_ids["supplement"],
            needs_review=0 if verified else 1,
        )
        n += 1
    return n


def run(max_papers: int | None = None) -> None:
    conn = get_connection()
    try:
        rows = papers_by_status(conn, ["screened_relevant"], limit=max_papers)
        rows = [r for r in rows if (CHUNKS_DIR / f"{r['paper_id']}.json").exists()]
        print(f"Extracting attempts from {len(rows)} screened-relevant papers with chunk packets...")

        consecutive_failures = 0
        n_attempts = n_papers_done = 0
        for i, row in enumerate(rows, start=1):
            paper_id = row["paper_id"]
            packet = json.loads((CHUNKS_DIR / f"{paper_id}.json").read_text())
            try:
                n = extract_paper(conn, paper_id, packet)
                consecutive_failures = 0
            except llm_client.LLMError as e:
                consecutive_failures += 1
                print(f"  [extract] LLM call failed for {paper_id} ({consecutive_failures} in a row): {e}", flush=True)
                if consecutive_failures >= MAX_CONSECUTIVE_LLM_FAILURES:
                    conn.commit()
                    print(f"FATAL: {consecutive_failures} consecutive LLM failures -- the LLM server "
                          f"({llm_client.DEFAULT_BASE_URL}) is very likely down or wedged. Stopping. "
                          f"Committed {n_papers_done} papers' worth of attempts so far.", flush=True)
                    sys.exit(1)
                continue

            conn.execute("UPDATE papers SET processing_status='extraction_complete', last_checked_at=? WHERE paper_id=?",
                         (now_iso(), paper_id))
            n_attempts += n
            n_papers_done += 1
            if i % 10 == 0:
                conn.commit()
                print(f"  ...{i}/{len(rows)} papers, {n_attempts} attempts extracted so far", flush=True)

        conn.commit()
        print(f"Done. {n_attempts} attempts extracted from {n_papers_done} papers.")
    finally:
        conn.close()


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(max_papers=limit)
