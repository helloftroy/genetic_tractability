"""Route C: negative-enriched search for failed manipulation attempts (spec 3C).

Failure cases are especially valuable (spec principle #1: "Failure is
data"). Each near-exact failure phrase is combined with a broad organism
term; results are kept even if the venue looks obscure, per spec.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from candidate_store import CandidateStore
from common import epmc_search, parse_epmc_record

FAILURE_PHRASES = [
    '"failed to transform"',
    '"unable to transform"',
    '"could not be transformed"',
    '"no transformants"',
    '"attempts to transform"',
    '"transformation was unsuccessful"',
    '"electroporation failed"',
    '"conjugation failed"',
    '"recalcitrant to transformation"',
    '"resistant to transformation"',
    '"unable to introduce plasmid"',
    '"could not introduce DNA"',
    '"Cas9 toxicity"',
    '"Cas9 was toxic"',
    '"plasmid could not replicate"',
    '"no colonies were obtained"',
]

ORGANISM_CONTEXT_TERMS = [
    "bacteria", "strain", "microorganism", "marine",
    '"environmental isolate"', '"non-model"',
]

PER_QUERY = 15


def main() -> None:
    store = CandidateStore()
    added = 0
    seen_this_run = set()

    context = " OR ".join(ORGANISM_CONTEXT_TERMS)
    for phrase in FAILURE_PHRASES:
        query = f"{phrase} AND ({context})"
        records = epmc_search(query, max_results=PER_QUERY)
        for rec in records:
            parsed = parse_epmc_record(rec)
            if not parsed["title"]:
                continue
            is_review = "review" in parsed["pub_type_list"].lower()
            paper_id = store.add(
                title=parsed["title"],
                doi=parsed["doi"],
                pmid=parsed["pmid"],
                pmcid=parsed["pmcid"],
                year=parsed["year"],
                journal=parsed["journal"],
                authors=parsed["authors"],
                source_database="europe_pmc",
                discovery_route="negative_keyword",
                discovery_query=query,
                is_review=is_review,
                full_text_available=parsed["is_open_access"],
                processing_status="review_seed" if is_review else "discovered",
                notes="failure-enriched search: keep even if obscure venue",
            )
            if paper_id not in seen_this_run:
                seen_this_run.add(paper_id)
                added += 1

    store.save()
    print(f"Negative-keyword route: {added} unique new/enriched candidate papers this run")
    print(f"candidate_papers.csv now has {len(store.all_rows())} rows")


if __name__ == "__main__":
    main()
