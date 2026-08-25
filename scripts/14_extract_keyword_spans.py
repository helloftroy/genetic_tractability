# -*- coding: utf-8 -*-
"""Deterministic (no LLM) keyword-anchored span extraction (spec: use
keywords to find the right spots, don't rely on the LLM for that).

For every paper that abstract triage (script 13) marked yes/maybe: fetch
full text if open access, else fall back to the abstract; split into
sentences; tag each sentence against keyword_lexicon's categories;
regex-extract accession numbers and culture-collection strain IDs
directly from the full text. Writes one compact JSON "evidence packet"
per paper to keyword_spans/<paper_id>.json -- this file, not the raw
paper, is all script 15's LLM call ever sees.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, cache_only_miss_count, epmc_fulltext_xml, epmc_lookup_record, read_csv_dicts, write_csv_dicts
from keyword_lexicon import find_accessions, find_culture_collection_strains, tag_sentence
from text_sections import sentences_for_paper

SPANS_DIR = DATA_DIR / "keyword_spans"
SPANS_DIR.mkdir(parents=True, exist_ok=True)

MAX_PER_CATEGORY = 12  # keeps the step-15 prompt short; these are the categories with the most signal
PRIORITY_CATEGORIES = ["manipulation", "success", "failure", "wild_type", "not_wild_type",
                        "strain", "accession", "isolation_source"]

INDEX_FIELDNAMES = [
    "paper_id", "text_source", "n_sentences_total", "n_tagged_sentences",
    "n_manipulation", "n_success", "n_failure", "n_wild_type", "n_not_wild_type",
    "regex_accessions", "regex_strains", "has_signal",
]


def build_packet(paper_id: str, title: str, abstract: str, jats_xml: str | None) -> dict:
    sentences, source = sentences_for_paper(abstract, jats_xml)
    full_text = " ".join(s for _, _, s in sentences)

    by_category: dict[str, list[dict]] = {cat: [] for cat in PRIORITY_CATEGORIES}
    seen_sentences: set[str] = set()
    n_tagged = 0

    for section, para_idx, sentence in sentences:
        hits = tag_sentence(sentence)
        if not hits:
            continue
        n_tagged += 1
        key = sentence.strip().lower()
        if key in seen_sentences:
            continue
        seen_sentences.add(key)
        for cat in hits:
            if cat in by_category and len(by_category[cat]) < MAX_PER_CATEGORY:
                by_category[cat].append({
                    "section": section, "paragraph": para_idx, "sentence": sentence,
                    "matched_terms": hits[cat],
                })

    return {
        "paper_id": paper_id,
        "title": title,
        "text_source": source,
        "n_sentences_total": len(sentences),
        "n_tagged_sentences": n_tagged,
        "spans_by_category": by_category,
        "regex_accessions": find_accessions(full_text),
        "regex_strains": find_culture_collection_strains(full_text),
    }


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10_000
    triage = read_csv_dicts(DATA_DIR / "abstract_triage.csv")
    papers = {p["paper_id"]: p for p in read_csv_dicts(DATA_DIR / "candidate_papers.csv")}

    to_process = [t for t in triage if t["decision"] in ("yes", "maybe") and t["abstract_available"] == "True"]
    already_done = {p.stem for p in SPANS_DIR.glob("*.json")}
    to_process = [t for t in to_process if t["paper_id"] not in already_done][:limit]

    print(f"Building keyword-span packets for {len(to_process)} papers "
          f"(already done: {len(already_done)})...")

    index_rows = []
    n_with_signal = 0

    for i, t in enumerate(to_process, start=1):
        paper_id = t["paper_id"]
        paper = papers.get(paper_id, {})
        rec = epmc_lookup_record(paper.get("doi", ""), paper.get("pmid", ""), paper.get("title", ""))
        if not rec:
            continue
        jats_xml = epmc_fulltext_xml(rec["pmcid"]) if rec.get("is_open_access") and rec.get("pmcid") else None

        packet = build_packet(paper_id, rec.get("title") or paper.get("title", ""), rec.get("abstract", ""), jats_xml)
        (SPANS_DIR / f"{paper_id}.json").write_text(json.dumps(packet, indent=2))

        cat_counts = {cat: len(v) for cat, v in packet["spans_by_category"].items()}
        has_signal = cat_counts.get("manipulation", 0) > 0 and (
            cat_counts.get("success", 0) > 0 or cat_counts.get("failure", 0) > 0
            or cat_counts.get("strain", 0) > 0
        )
        if has_signal:
            n_with_signal += 1

        index_rows.append({
            "paper_id": paper_id, "text_source": packet["text_source"],
            "n_sentences_total": packet["n_sentences_total"], "n_tagged_sentences": packet["n_tagged_sentences"],
            "n_manipulation": cat_counts.get("manipulation", 0), "n_success": cat_counts.get("success", 0),
            "n_failure": cat_counts.get("failure", 0), "n_wild_type": cat_counts.get("wild_type", 0),
            "n_not_wild_type": cat_counts.get("not_wild_type", 0),
            "regex_accessions": sum(len(v) for v in packet["regex_accessions"].values()),
            "regex_strains": len(packet["regex_strains"]),
            "has_signal": has_signal,
        })

        if i % 25 == 0:
            print(f"  ...{i}/{len(to_process)} (with_signal={n_with_signal})")

    existing_index = read_csv_dicts(DATA_DIR / "keyword_spans_index.csv")
    existing_ids = set(r["paper_id"] for r in existing_index)
    combined = existing_index + [r for r in index_rows if r["paper_id"] not in existing_ids]
    write_csv_dicts(DATA_DIR / "keyword_spans_index.csv", combined, INDEX_FIELDNAMES)

    print(f"Done. {len(index_rows)} packets built this run, {n_with_signal} with real manipulation+outcome/strain signal.")
    print(f"Wrote {SPANS_DIR}/*.json and {DATA_DIR / 'keyword_spans_index.csv'}")
    miss_count = cache_only_miss_count()
    if miss_count:
        print(f"WARNING: {miss_count} lookups were cache misses (GENETIC_TRACTABILITY_CACHE_ONLY=1 -- "
              f"skipped instantly rather than hitting the network). This batch was not fully warmed by "
              f"run_prefetch.sbatch -- re-run it with the SAME BATCH_SIZE before extraction to cover these.")


if __name__ == "__main__":
    main()
