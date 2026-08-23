# -*- coding: utf-8 -*-
"""Step 3c: qwen structures the keyword-anchored spans (script 14) into
manipulation_observations rows. qwen never sees the raw paper -- only the
sentences the keyword lexicon already flagged, grouped by category, plus
any regex-found accessions/strain IDs as hints. This keeps prompts short
(the whole point of the keyword-first design) and gives every returned
evidence_text a verbatim source sentence to verify against.

Verification mirrors fair_ocean_agent's evidence.py philosophy: a
returned evidence_text that isn't a real substring of a provided sentence
is not silently trusted -- the record is kept (per spec: don't silently
drop) but flagged qc_flags=evidence_unverified for manual review.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm_client
from common import DATA_DIR, make_observation_id, read_csv_dicts, write_csv_dicts

SPANS_DIR = DATA_DIR / "keyword_spans"
OUT_PATH = DATA_DIR / "manipulation_observations_auto.csv"

OBS_FIELDNAMES = [
    "observation_id", "paper_id", "organism_name", "strain_name", "organism_domain",
    "wild_type_status", "wild_type_evidence",
    "manipulation_category", "manipulation_detail",
    "outcome", "failure_reason",
    "evidence_text", "section_name",
    "genome_accession", "genome_match_status",
    "marine_status", "isolation_source", "environment",
    "qc_flags", "notes",
    "extraction_method", "llm_model",
]

MANIPULATION_CATEGORIES = [
    "electroporation", "conjugation", "natural transformation", "chemical transformation",
    "transduction", "plasmid introduction", "plasmid maintenance", "heterologous expression",
    "allelic exchange", "homologous recombination", "recombineering", "transposon mutagenesis",
    "CRISPR-Cas9", "other CRISPR-Cas systems", "genome editing", "stable genomic integration",
    "gene knockout", "gene knock-in", "other",
]
OUTCOME_VALUES = ["success", "failure", "partial", "mixed", "unclear"]
WT_VALUES = ["yes", "no", "unclear"]
DOMAIN_VALUES = ["bacteria", "archaea", "eukaryota"]

SYSTEM_PROMPT = f"""You extract structured records from pre-selected sentences of a microbiology paper \
about attempts to genetically manipulate a microorganism.

Rules:
1. Output ONLY a JSON array (use [] if nothing qualifies). No markdown, no commentary.
2. One array element = ONE organism/strain tested with ONE manipulation technique with ONE outcome. \
If the paper reports multiple strains, or the same strain tried with multiple techniques (e.g. \
electroporation failed, conjugation succeeded), output SEPARATE elements for each -- never combine them.
3. evidence_text MUST be copied character-for-character from the "SENTENCES" provided below -- pick the \
single best sentence (or exact substring of it). NEVER paraphrase, summarize, translate, or invent text. \
If you cannot find a sentence that actually supports a field, leave that field as "" (empty string) rather \
than guessing.
4. manipulation_category must be exactly one of: {MANIPULATION_CATEGORIES}
5. outcome must be exactly one of: {OUTCOME_VALUES}
6. wild_type_status must be exactly one of: {WT_VALUES} ("no" = explicitly an engineered/mutant/domesticated \
derivative used as the manipulation target; "unclear" if not stated)
7. organism_domain must be exactly one of: {DOMAIN_VALUES}
8. genome_accession: only fill this in if one of the REGEX_ACCESSIONS or REGEX_STRAINS hints below clearly \
belongs to the organism/strain in this record; otherwise leave "".

Each element's JSON shape:
{{"organism_name": "", "strain_name": "", "organism_domain": "", "wild_type_status": "", \
"wild_type_evidence": "", "manipulation_category": "", "outcome": "", "failure_reason": "", \
"evidence_text": "", "genome_accession": ""}}"""

USER_TEMPLATE = """PAPER TITLE: {title}

SENTENCES (grouped by what keyword matched; [section] tag shown per sentence):
{sentences_block}

REGEX_ACCESSIONS found in this paper's text: {accessions}
REGEX_STRAINS (culture-collection IDs) found in this paper's text: {strains}

Return the JSON array now."""


def normalize_sentence(s: str) -> str:
    return " ".join(s.lower().split())


def build_prompt_and_lookup(packet: dict) -> tuple[str, set[str]]:
    blocks = []
    all_sentences = set()
    for cat, items in packet["spans_by_category"].items():
        if not items:
            continue
        blocks.append(f"\n[{cat}]")
        for item in items:
            blocks.append(f"  - [{item['section']}] {item['sentence']}")
            all_sentences.add(normalize_sentence(item["sentence"]))
    sentences_block = "\n".join(blocks) if blocks else "(none)"

    accessions_flat = [a for lst in packet["regex_accessions"].values() for a in lst]
    user = USER_TEMPLATE.format(
        title=packet["title"], sentences_block=sentences_block,
        accessions=", ".join(accessions_flat) or "(none)",
        strains=", ".join(packet["regex_strains"]) or "(none)",
    )
    return user, all_sentences


def verify_evidence(evidence_text: str, sentence_lookup: set[str]) -> bool:
    if not evidence_text:
        return False
    needle = normalize_sentence(evidence_text)
    return any(needle in hay or hay in needle for hay in sentence_lookup)


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10_000
    index = read_csv_dicts(DATA_DIR / "keyword_spans_index.csv")
    already_processed = set(r["paper_id"] for r in read_csv_dicts(OUT_PATH))

    candidates = [r for r in index if r["has_signal"] == "True" and r["paper_id"] not in already_processed][:limit]
    print(f"Running structured extraction on {len(candidates)} papers with keyword signal...")

    rows = read_csv_dicts(OUT_PATH)
    n_records = 0
    n_unverified = 0
    n_papers_with_records = 0

    for i, entry in enumerate(candidates, start=1):
        paper_id = entry["paper_id"]
        packet_path = SPANS_DIR / f"{paper_id}.json"
        if not packet_path.exists():
            continue
        packet = json.loads(packet_path.read_text())

        user_prompt, sentence_lookup = build_prompt_and_lookup(packet)
        try:
            raw = llm_client.chat(SYSTEM_PROMPT, user_prompt, max_tokens=1500)
            parsed = llm_client.extract_json(raw)
        except llm_client.LLMError:
            parsed = None

        if not isinstance(parsed, list):
            continue

        paper_had_record = False
        for j, rec in enumerate(parsed, start=1):
            if not isinstance(rec, dict) or not rec.get("organism_name"):
                continue
            evidence_text = str(rec.get("evidence_text", "")).strip()
            verified = verify_evidence(evidence_text, sentence_lookup)
            qc_flags = "" if verified else "evidence_unverified"

            manip_cat = rec.get("manipulation_category", "")
            outcome = rec.get("outcome", "")
            wt_status = rec.get("wild_type_status", "")
            domain = rec.get("organism_domain", "")
            manip_detail = ""
            if manip_cat not in MANIPULATION_CATEGORIES:
                # Don't silently drop the model's own (possibly informative) phrasing --
                # move it to manipulation_detail and coerce the controlled-vocab field to
                # "other" so downstream category counts stay meaningful.
                manip_detail = manip_cat
                manip_cat = "other"
                qc_flags = (qc_flags + " manipulation_category_uncertain").strip()
            if outcome not in OUTCOME_VALUES:
                qc_flags = (qc_flags + " outcome_uncertain").strip()
                outcome = "unclear"
            if wt_status not in WT_VALUES:
                qc_flags = (qc_flags + " wild_type_uncertain").strip()
                wt_status = "unclear"
            if domain not in DOMAIN_VALUES:
                domain = "bacteria"

            rows.append({
                "observation_id": make_observation_id(paper_id, j),
                "paper_id": paper_id,
                "organism_name": rec.get("organism_name", ""),
                "strain_name": rec.get("strain_name", ""),
                "organism_domain": domain,
                "wild_type_status": wt_status,
                "wild_type_evidence": rec.get("wild_type_evidence", ""),
                "manipulation_category": manip_cat,
                "manipulation_detail": manip_detail,
                "outcome": outcome,
                "failure_reason": rec.get("failure_reason", ""),
                "evidence_text": evidence_text,
                "section_name": packet.get("text_source", ""),
                "genome_accession": rec.get("genome_accession", ""),
                "genome_match_status": "not_checked",
                "marine_status": "unknown",
                "isolation_source": "unknown",
                "environment": "unknown",
                "qc_flags": qc_flags,
                "notes": "",
                "extraction_method": "automated_qwen",
                "llm_model": llm_client.DEFAULT_MODEL,
            })
            n_records += 1
            paper_had_record = True
            if not verified:
                n_unverified += 1
        if paper_had_record:
            n_papers_with_records += 1

        if i % 20 == 0:
            write_csv_dicts(OUT_PATH, rows, OBS_FIELDNAMES)
            print(f"  ...{i}/{len(candidates)} papers, {n_records} records so far ({n_unverified} unverified)")

    write_csv_dicts(OUT_PATH, rows, OBS_FIELDNAMES)
    print(f"Done. {n_records} records from {n_papers_with_records}/{len(candidates)} papers "
          f"({n_unverified} with unverified evidence_text, flagged not dropped).")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
