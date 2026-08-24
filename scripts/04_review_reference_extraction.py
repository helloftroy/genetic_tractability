"""Extract referenced primary papers from each review seed (spec 3A steps 3-4).

Uses Europe PMC's structured /references endpoint (no XML parsing needed)
for every review in review_seeds.csv. Reference records commonly lack a
DOI/PMID (older citations, book chapters, etc.) -- those are skipped since
candidate_papers dedup requires at least a DOI, PMID, or title.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from candidate_store import CandidateStore
from common import DATA_DIR, epmc_references, read_csv_dicts


def epmc_source_for_paper(row: dict) -> tuple[str, str] | None:
    if row.get("pmid"):
        return "MED", row["pmid"]
    return None


def main() -> None:
    store = CandidateStore()
    reviews = read_csv_dicts(DATA_DIR / "review_seeds.csv")
    added = 0
    reviews_with_refs = 0

    for i, review in enumerate(reviews, start=1):
        if i % 10 == 0 or i == len(reviews):
            print(f"  [{i}/{len(reviews)}] reviews processed (refs added so far: {added})", flush=True)
            store.save()  # periodic checkpoint -- this loop can run long over ~150+ reviews
        source_id = epmc_source_for_paper(review)
        if not source_id:
            continue
        source, ext_id = source_id
        refs = epmc_references(source, ext_id)
        if refs:
            reviews_with_refs += 1
        for ref in refs:
            title = (ref.get("title") or "").strip().rstrip(".")
            doi = ref.get("doi") or ""
            pmid = ref.get("id") if ref.get("source") == "MED" else ""
            year = str(ref.get("pubYear") or "")
            journal = ref.get("journalAbbreviation") or ""
            authors = ref.get("authorString") or ""
            if not title and not doi and not pmid:
                continue
            store.add(
                title=title or f"[untitled reference, doi={doi or 'n/a'}]",
                doi=doi,
                pmid=pmid or "",
                year=year,
                journal=journal,
                authors=authors,
                source_database="europe_pmc_references",
                discovery_route="review_reference",
                discovery_query=f"references of {review['paper_id']} ({review.get('title', '')[:80]})",
                review_seed_doi=review.get("doi", "") or review["paper_id"],
                processing_status="discovered",
                notes="",
            )
            added += 1

    store.save()
    print(f"Reviews processed: {len(reviews)}; reviews with a resolvable reference list: {reviews_with_refs}")
    print(f"Reference rows added/enriched: {added}")
    print(f"candidate_papers.csv now has {len(store.all_rows())} rows")


if __name__ == "__main__":
    main()
