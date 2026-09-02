# -*- coding: utf-8 -*-
"""Forward/backward citation expansion via NCBI ELink (spec sections 11-13).
NOT OpenAlex -- see run_engineering_discovery.py's module docstring.

"High-value seed paper" = a review-derived paper with a PMID (discovery_
source=review -- spec section 6 explicitly calls these out as citation-
expansion starting nodes), or a paper that has already produced at least
one non-"unclear"-outcome engineering_attempts row (a confirmed-real
result, the strongest possible signal). Deliberately does NOT crawl the
entire citation graph: default 1 hop forward + 1 hop backward from the
CURRENT seed set only (spec section 13); --citation-depth 2 repeats the
hop using whatever new papers hop 1 found as the next seed set, still
capped, never unbounded recursion.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from attempt_db import get_connection
from discovery_v2 import _ingest_pmids
from ncbi_eutils import LINKNAME_CITED_BY, LINKNAME_REFERENCES, elink


def high_value_seed_pmids(conn) -> list[str]:
    review_seeds = conn.execute(
        "SELECT DISTINCT pmid FROM papers WHERE pmid != '' AND discovery_sources_json LIKE '%\"review\"%'"
    ).fetchall()
    confirmed = conn.execute(
        "SELECT DISTINCT p.pmid FROM papers p JOIN engineering_attempts a ON a.paper_id = p.paper_id "
        "WHERE p.pmid != '' AND a.outcome != 'unclear'"
    ).fetchall()
    return sorted({r["pmid"] for r in review_seeds} | {r["pmid"] for r in confirmed})


def expand_citations(conn, seed_pmids: list[str], depth: int = 1, max_seeds: int | None = None) -> int:
    if depth <= 0 or not seed_pmids:
        return 0
    if max_seeds:
        seed_pmids = seed_pmids[:max_seeds]

    print(f"Citation expansion: {len(seed_pmids)} seed papers, depth={depth}...")
    newly_discovered_pmids: set[str] = set()
    total = 0

    for i, seed_pmid in enumerate(seed_pmids, start=1):
        cited_by = elink(seed_pmid, LINKNAME_CITED_BY)
        n1 = _ingest_pmids(conn, cited_by, "cited_by", f"cited_by:{seed_pmid}")
        _tag_source_seed(conn, cited_by, seed_pmid)

        refs = elink(seed_pmid, LINKNAME_REFERENCES)
        n2 = _ingest_pmids(conn, refs, "reference", f"reference:{seed_pmid}")
        _tag_source_seed(conn, refs, seed_pmid)

        newly_discovered_pmids.update(cited_by)
        newly_discovered_pmids.update(refs)
        total += n1 + n2
        if i % 10 == 0 or i == len(seed_pmids):
            print(f"  ...{i}/{len(seed_pmids)} seeds expanded ({total} papers ingested so far)", flush=True)

    print(f"Citation expansion hop complete. {total} papers ingested (depth remaining: {depth - 1}).")
    if depth > 1 and newly_discovered_pmids:
        total += expand_citations(conn, sorted(newly_discovered_pmids), depth=depth - 1)
    return total


def _tag_source_seed(conn, pmids: list[str], seed_pmid: str) -> None:
    """Records which seed paper led to each citation-expanded hit (spec
    sections 11/12: source_seed_pmid). Uses the same upsert_paper merge
    semantics as discovery_v2 -- appends to source_seed_pmids_json rather
    than overwriting, since a paper can be reached from multiple seeds."""
    from attempt_db import upsert_paper
    from discovery_v2 import make_paper_id

    if not pmids:
        return
    placeholders = ", ".join("?" for _ in pmids)
    rows = conn.execute(f"SELECT paper_id, pmid FROM papers WHERE pmid IN ({placeholders})", pmids).fetchall()
    for row in rows:
        upsert_paper(conn, row["paper_id"], source_seed_pmids=seed_pmid)
    conn.commit()


def run(depth: int = 1, max_seeds: int | None = None) -> None:
    conn = get_connection()
    try:
        seeds = high_value_seed_pmids(conn)
        expand_citations(conn, seeds, depth=depth, max_seeds=max_seeds)
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--citation-depth", type=int, default=1)
    parser.add_argument("--max-seeds", type=int, default=None)
    args = parser.parse_args()
    run(depth=args.citation_depth, max_seeds=args.max_seeds)
