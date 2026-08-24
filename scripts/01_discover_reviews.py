"""Route A: review-paper seed discovery (spec section 3A).

Searches Europe PMC, restricted to review-type articles, across ~12 topic
queries covering genetic manipulation/toolboxes/domestication of non-model
and marine microbes. Keeps the top few most-cited/relevant reviews per topic
until ~10-20 unique reviews are collected, writes review_seeds.csv, and adds
each review to candidate_papers.csv (needed as a discovery seed even though
reviews are excluded from the final phenotype evidence set).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from candidate_store import CandidateStore
from common import DATA_DIR, epmc_search, parse_epmc_record, read_csv_dicts, write_csv_dicts

REVIEW_TOPICS = [
    "genetic manipulation of non-model bacteria",
    "genetic engineering of marine bacteria",
    "microbial genetic toolbox",
    "genetic domestication of non-model microorganisms",
    "natural competence in bacteria",
    "transformation of environmental bacteria",
    "conjugation in non-model bacteria",
    "CRISPR engineering of non-model bacteria",
    "genome editing in non-model microorganisms",
    "synthetic biology chassis development",
    "genetic tools for extremophiles",
    "genetic tools for marine microorganisms",
    # Round 2: broader net + older/historical terminology (spec principle
    # #8: don't restrict discovery to modern "synthetic biology" phrasing).
    "genetic systems for bacteria",
    "gene transfer systems in bacteria",
    "electroporation protocols for bacteria",
    "conjugative gene transfer in environmental bacteria",
    "genetic manipulation of cyanobacteria",
    "genetic tools for anaerobic bacteria",
    "genetic tools for actinomycetes",
    "genetic tools for Vibrio species",
    "molecular genetics of marine microorganisms",
    "genetic transformation of gram-positive bacteria",
    "genetic transformation of gram-negative bacteria",
    "host range of broad host range plasmids",
    "CRISPR interference in bacteria",
    "recombineering in bacteria",
    "genetic engineering of unculturable bacteria",
    "restriction modification barriers to transformation",
    "genetic tools for methanogens",
    "genetic tools for archaea",
    "domestication of industrial microorganisms",
    "expanding the genetic toolbox of bacteria",
    # Round 3: organism-specific topics. Review-table extraction (script 12)
    # is the highest-precision candidate source this pipeline has, and a
    # genus-specific review is far more likely to carry a real "Host |
    # Method | Reference" table than a generic one -- worth the extra
    # queries even though many will overlap with round 1/2's hits.
    "genetic tools for Streptomyces",
    "genetic tools for Rhodococcus",
    "genetic tools for Clostridium",
    "genetic tools for Synechocystis",
    "genetic tools for Pseudomonas",
    "genetic tools for Bacillus",
    "genetic tools for Mycobacterium",
    "genetic tools for Acinetobacter",
    "genetic tools for Corynebacterium",
    "genetic tools for Lactobacillus",
    "genetic tools for Bifidobacterium",
    "genetic tools for Xanthomonas",
    "genetic tools for Agrobacterium",
    "genetic tools for Rhizobium",
    "genetic tools for Klebsiella",
    "genetic tools for Salmonella",
    "genetic tools for Listeria",
    "genetic tools for Staphylococcus",
    "genetic tools for Shewanella",
    "genetic tools for Halomonas",
    "genetic tools for Sulfolobus",
    "genetic tools for Haloferax",
    "genetic tools for Thermus",
    "genetic tools for Deinococcus",
    "genetic tools for Zymomonas",
    "genetic tools for Cupriavidus",
    "genetic tools for Ralstonia",
    # Round 3: technique-specific topics not covered above.
    "markerless gene deletion in bacteria",
    "counterselection markers for bacteria",
    "Golden Gate assembly for bacterial engineering",
    "riboswitch selection markers bacteria",
    "phage-based genetic tools for bacteria",
    "synthetic biology parts for bacteria",
    "genome minimization in bacteria",
    "inducible expression systems for bacteria",
    "genetic circuit design in bacteria",
    "base editing in bacteria",
    "serine integrase genome engineering bacteria",
]

TARGET_TOTAL_REVIEWS = 100
PER_TOPIC = 10
FETCH_PER_TOPIC = 50

REVIEW_SEED_FIELDNAMES = [
    "paper_id", "title", "doi", "pmid", "year", "journal",
    "topic_area", "discovery_query", "notes",
]

ORGANISM_TERMS = [
    "bacter", "microb", "archae", "prokary", "extremophil", "marine",
    "vibrio", "pseudomonas", "cyanobacter", "actinomycete", "archaea",
    "microorganism", "isolate", "strain",
]
MANIPULATION_TERMS = [
    "genetic", "transform", "crispr", "editing", "engineer", "toolbox",
    "gene", "plasmid", "conjugation", "competence", "recombin", "chassis",
    "transposon", "electropor", "domestic",
]


def is_relevant(title: str) -> bool:
    t = title.lower()
    return any(term in t for term in ORGANISM_TERMS) and any(term in t for term in MANIPULATION_TERMS)


SORT_PASSES = ["", "CITED desc"]  # relevance, then citation-sorted to surface older influential reviews
OLD_YEAR_PER_TOPIC = 5
OLD_YEAR_RANGE = "1985 TO 2018"  # explicit older-literature pass: relevance ranking alone skews heavily to 2025/2026


def main() -> None:
    store = CandidateStore()
    review_rows = read_csv_dicts(DATA_DIR / "review_seeds.csv")  # accumulate, don't clobber prior runs
    seen_paper_ids = set(r["paper_id"] for r in review_rows)
    n_before = len(review_rows)

    for ti, topic in enumerate(REVIEW_TOPICS, start=1):
        print(f"  [relevance/cited pass {ti}/{len(REVIEW_TOPICS)}] {topic!r} "
              f"(reviews so far: {len(review_rows)})", flush=True)
        query = f'({topic}) AND (PUB_TYPE:"Review")'
        added_for_topic = 0
        for sort in SORT_PASSES:
            if added_for_topic >= PER_TOPIC:
                break
            records = epmc_search(query, max_results=FETCH_PER_TOPIC, sort=sort)
            for rec in records:
                if added_for_topic >= PER_TOPIC:
                    break
                parsed = parse_epmc_record(rec)
                if not parsed["title"] or not is_relevant(parsed["title"]):
                    continue
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
                    discovery_query=f"review_topic_search ({sort or 'relevance'}): {query}",
                    is_review=True,
                    full_text_available=parsed["is_open_access"],
                    processing_status="review_seed",
                    notes="Discovered as review seed (route A)",
                )
                if paper_id not in seen_paper_ids:
                    seen_paper_ids.add(paper_id)
                    review_rows.append({
                        "paper_id": paper_id,
                        "title": parsed["title"],
                        "doi": parsed["doi"],
                        "pmid": parsed["pmid"],
                        "year": parsed["year"],
                        "journal": parsed["journal"],
                        "topic_area": topic,
                        "discovery_query": query,
                        "notes": "open_access" if parsed["is_open_access"] else "not_open_access",
                    })
                    added_for_topic += 1

        write_csv_dicts(DATA_DIR / "review_seeds.csv", review_rows, REVIEW_SEED_FIELDNAMES)
        store.save()  # checkpoint after every topic -- avoids losing a whole run to a mid-run crash/timeout

    # Explicit older-literature pass: pure relevance/citation ranking above
    # skewed heavily to 2025/2026 (recency bias in both), so force recall
    # of pre-2019 reviews per topic with an explicit year-range filter.
    for ti, topic in enumerate(REVIEW_TOPICS, start=1):
        print(f"  [older-literature pass {ti}/{len(REVIEW_TOPICS)}] {topic!r} "
              f"(reviews so far: {len(review_rows)})", flush=True)
        query = f'({topic}) AND (PUB_TYPE:"Review") AND (PUB_YEAR:[{OLD_YEAR_RANGE}])'
        records = epmc_search(query, max_results=FETCH_PER_TOPIC)
        added_for_topic = 0
        for rec in records:
            if added_for_topic >= OLD_YEAR_PER_TOPIC:
                break
            parsed = parse_epmc_record(rec)
            if not parsed["title"] or not is_relevant(parsed["title"]):
                continue
            paper_id = store.add(
                title=parsed["title"], doi=parsed["doi"], pmid=parsed["pmid"], pmcid=parsed["pmcid"],
                year=parsed["year"], journal=parsed["journal"], authors=parsed["authors"],
                source_database="europe_pmc", discovery_route="broad_keyword",
                discovery_query=f"review_topic_search (older-literature pass): {query}",
                is_review=True, full_text_available=parsed["is_open_access"],
                processing_status="review_seed", notes="Discovered as review seed (route A, older-literature pass)",
            )
            if paper_id not in seen_paper_ids:
                seen_paper_ids.add(paper_id)
                review_rows.append({
                    "paper_id": paper_id, "title": parsed["title"], "doi": parsed["doi"],
                    "pmid": parsed["pmid"], "year": parsed["year"], "journal": parsed["journal"],
                    "topic_area": topic, "discovery_query": query,
                    "notes": "open_access" if parsed["is_open_access"] else "not_open_access",
                })
                added_for_topic += 1

    write_csv_dicts(DATA_DIR / "review_seeds.csv", review_rows, REVIEW_SEED_FIELDNAMES)
    store.save()
    print(f"Reviews collected this run: {len(review_rows) - n_before} new (target total ~{TARGET_TOTAL_REVIEWS})")
    print(f"Total reviews in review_seeds.csv: {len(review_rows)}")
    print(f"Wrote {DATA_DIR / 'review_seeds.csv'}")
    print(f"candidate_papers.csv now has {len(store.all_rows())} rows")


if __name__ == "__main__":
    main()
