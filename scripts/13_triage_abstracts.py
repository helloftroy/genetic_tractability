# -*- coding: utf-8 -*-
"""Cheap qwen triage over abstracts only: does this paper look like it
describes an attempt to genetically manipulate a microorganism?

This is the one place qwen reads free text without a keyword anchor --
deliberately kept to an abstract (short) rather than a full paper, and
used only to gate which candidates get the more expensive keyword-span +
structured-extraction treatment (scripts 14/15), not to extract any
fields itself.

Accumulates into abstract_triage.csv across runs (like the review
discovery scripts) so re-running only processes newly-added candidates.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm_client
from batch_selection import select_triage_batch
from common import DATA_DIR, cache_only_miss_count, epmc_lookup_record, read_csv_dicts, write_csv_dicts

TRIAGE_FIELDNAMES = ["paper_id", "title", "decision", "reason", "abstract_available"]

SYSTEM_PROMPT = (
    "You are screening scientific paper abstracts for a literature-mining pipeline. "
    "Answer ONLY with a compact JSON object: "
    '{"decision": "yes"|"no"|"maybe", "reason": "<max 12 words>"}. '
    "No other text, no markdown, no explanation outside the JSON."
)

USER_TEMPLATE = """Does this abstract describe an actual, hands-on ATTEMPT to genetically manipulate \
(e.g. transform, electroporate, conjugate, transduce, edit with CRISPR, knock out/in a gene, \
introduce or maintain a plasmid) a bacterium, archaeon, or unicellular microbial eukaryote -- \
regardless of whether the attempt succeeded or failed?

Answer "no" if the abstract is purely about: genome sequencing/bioinformatics with no wet-lab \
manipulation, a naturally-occurring CRISPR/defense system described with no engineering attempt, \
clinical/epidemiological surveillance with no lab manipulation, or manipulating only a plant/animal \
(even if a bacterium like Agrobacterium was used as a delivery tool).
Answer "maybe" if genuinely ambiguous from the abstract alone.

Title: {title}

Abstract: {abstract}"""


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    batch = select_triage_batch(limit)
    print(f"Triaging {len(batch)} papers (qwen abstract-only screen)...")

    rows = read_csv_dicts(DATA_DIR / "abstract_triage.csv")
    n_yes = n_no = n_maybe = n_skipped = 0

    for i, paper in enumerate(batch, start=1):
        rec = epmc_lookup_record(paper.get("doi", ""), paper.get("pmid", ""), paper.get("title", ""))
        abstract = (rec or {}).get("abstract", "")
        title = paper.get("title", "")
        if not abstract:
            rows.append({"paper_id": paper["paper_id"], "title": title, "decision": "maybe",
                         "reason": "no abstract text available", "abstract_available": "False"})
            n_skipped += 1
            continue

        user = USER_TEMPLATE.format(title=title, abstract=abstract[:2500])
        try:
            raw = llm_client.chat(SYSTEM_PROMPT, user, max_tokens=80)
            parsed = llm_client.extract_json(raw)
        except llm_client.LLMError as e:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("decision") in ("yes", "no", "maybe"):
            decision = parsed["decision"]
            reason = str(parsed.get("reason", ""))[:150]
        else:
            decision, reason = "maybe", "LLM output unparseable, defaulting to maybe"

        rows.append({"paper_id": paper["paper_id"], "title": title, "decision": decision,
                     "reason": reason, "abstract_available": "True"})
        if decision == "yes":
            n_yes += 1
        elif decision == "no":
            n_no += 1
        else:
            n_maybe += 1

        if i % 20 == 0:
            write_csv_dicts(DATA_DIR / "abstract_triage.csv", rows, TRIAGE_FIELDNAMES)
            print(f"  ...{i}/{len(batch)} (yes={n_yes} no={n_no} maybe={n_maybe} skipped={n_skipped})")

    write_csv_dicts(DATA_DIR / "abstract_triage.csv", rows, TRIAGE_FIELDNAMES)
    print(f"Done. yes={n_yes} no={n_no} maybe={n_maybe} skipped_no_abstract={n_skipped}")
    print(f"Wrote {DATA_DIR / 'abstract_triage.csv'} ({len(rows)} total rows)")
    miss_count = cache_only_miss_count()
    if miss_count:
        print(f"WARNING: {miss_count} lookups were cache misses (GENETIC_TRACTABILITY_CACHE_ONLY=1 -- "
              f"skipped instantly rather than hitting the network). This batch was not fully warmed by "
              f"run_prefetch.sbatch -- re-run it with the SAME BATCH_SIZE before extraction to cover these.")


if __name__ == "__main__":
    main()
