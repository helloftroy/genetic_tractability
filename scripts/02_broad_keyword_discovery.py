"""Route B: broad literature keyword discovery (spec section 3B).

Runs each specified keyword query against Europe PMC (no pub-type
restriction -- primary papers are the point here), keeps the top N by
relevance, and adds them to candidate_papers.csv with
discovery_route=broad_keyword. Deliberately not restricted to "synthetic
biology" phrasing per spec instruction #8.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from candidate_store import CandidateStore
from common import epmc_search, parse_epmc_record

BROAD_QUERIES = [
    '"genetic manipulation" AND bacteria',
    '"genetic toolbox" AND bacteria',
    '"genetic tools" AND "non-model bacteria"',
    '"transformation protocol" AND bacteria',
    'electroporation AND bacteria',
    'conjugation AND "non-model bacteria"',
    '"natural competence" AND bacteria',
    '"natural transformation" AND bacteria',
    '"allelic exchange" AND bacteria',
    'recombineering AND bacteria',
    '"genome editing" AND bacteria',
    '"CRISPR-Cas9" AND bacteria',
    '"CRISPR editing" AND "non-model bacteria"',
    '"plasmid transformation" AND bacteria',
    '"heterologous expression" AND "non-model bacteria"',
    '"transposon mutagenesis" AND bacteria',
    # Round 2: techniques/phrasing not covered above.
    '"chemical transformation" AND bacteria',
    '"transduction" AND bacteria AND plasmid',
    '"plasmid maintenance" AND bacteria',
    '"stable integration" AND bacteria AND genome',
    '"gene knockout" AND bacteria',
    '"gene knock-in" AND bacteria',
    '"homologous recombination" AND bacteria AND genetic',
    '"CRISPR interference" AND bacteria',
    '"Cas12a" AND bacteria AND "genome editing"',
    '"suicide vector" AND bacteria',
    '"shuttle vector" AND bacteria AND transformation',
    '"markerless deletion" AND bacteria',
    '"counterselection" AND bacteria AND genetic',
    'electrotransformation AND bacteria',
    '"genetic transformation" AND "environmental isolate"',
    '"genetic transformation" AND "marine bacterium"',
]

PER_QUERY = 150


def main() -> None:
    store = CandidateStore()
    added = 0
    seen_this_run = set()

    for i, query in enumerate(BROAD_QUERIES, start=1):
        print(f"  [{i}/{len(BROAD_QUERIES)}] {query!r} (running total added: {added})", flush=True)
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
                discovery_route="broad_keyword",
                discovery_query=query,
                is_review=is_review,
                full_text_available=parsed["is_open_access"],
                processing_status="review_seed" if is_review else "discovered",
                notes="",
            )
            if paper_id not in seen_this_run:
                seen_this_run.add(paper_id)
                added += 1

        store.save()  # checkpoint after every query -- cheap (16 queries total), avoids losing a whole run to a mid-run crash/timeout

    print(f"Broad-keyword route: {added} unique new/enriched candidate papers this run")
    print(f"candidate_papers.csv now has {len(store.all_rows())} rows")


if __name__ == "__main__":
    main()
