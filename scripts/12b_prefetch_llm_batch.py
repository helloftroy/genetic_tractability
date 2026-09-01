# -*- coding: utf-8 -*-
"""Network-only cache warmer for the LLM stage (cluster split, mirrors
fair_ocean_agent's cluster/README.md "why two jobs" design exactly).

On a SLURM cluster, the GPU node running vLLM typically has NO internet
access, but scripts 13 (triage) and 14 (keyword-span extraction) both
need to fetch each paper's abstract/full text from Europe PMC (and,
as a fallback, an open-access PDF via OpenAlex -- see 14's own header)
before they can do their (non-network) LLM/regex work. This script does
ONLY those fetches, for the exact same batch script 13 would pick (same
batch_selection.select_triage_batch call), on the CPU/service node that
DOES have internet -- warming common.py's on-disk response cache
(data/cache/*.{json,txt,pdf}, keyed by request URL). Scripts 13/14 then
run unmodified on the GPU node: same
epmc_lookup_record()/epmc_fulltext_xml()/openalex_best_oa_pdf_url()/
cached_get_binary() calls, but every one now hits the warm cache and
never touches the network. No LLM calls happen here at all.

Must warm the SAME fallback chain script 14 uses (JATS XML, then OpenAlex
PDF, then abstract) -- warming only the JATS XML step would leave the PDF
fallback permanently unusable on the GPU node (CACHE_ONLY mode fails an
uncached lookup instantly rather than fetching), silently undoing the
whole point of adding that fallback.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from batch_selection import select_triage_batch
from common import cached_get_binary, epmc_fulltext_xml, epmc_lookup_record, openalex_best_oa_pdf_url


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    batch = select_triage_batch(limit)
    print(f"Prefetching abstract + (if OA) full text for {len(batch)} papers...")

    n_abstract = n_fulltext = n_pdf_fallback = n_failed = 0
    for i, paper in enumerate(batch, start=1):
        rec = epmc_lookup_record(paper.get("doi", ""), paper.get("pmid", ""), paper.get("title", ""))
        if not rec:
            n_failed += 1
            continue
        if rec.get("abstract"):
            n_abstract += 1
        got_fulltext = False
        if rec.get("is_open_access") and rec.get("pmcid"):
            xml = epmc_fulltext_xml(rec["pmcid"])
            if xml:
                n_fulltext += 1
                got_fulltext = True
        if not got_fulltext:
            doi = rec.get("doi") or paper.get("doi", "")
            pdf_url = openalex_best_oa_pdf_url(doi) if doi else None
            if pdf_url and cached_get_binary(pdf_url, "openalex_pdf"):
                n_pdf_fallback += 1
        if i % 25 == 0:
            print(f"  ...{i}/{len(batch)} (abstracts={n_abstract} fulltext={n_fulltext} "
                  f"pdf_fallback={n_pdf_fallback} failed_lookup={n_failed})")

    print(f"Done. abstracts cached={n_abstract}, PMC full text cached={n_fulltext}, "
          f"OpenAlex PDF fallback cached={n_pdf_fallback}, lookup failed={n_failed}")
    print("Cache warmed under data/cache/ -- sync this directory to the GPU node's filesystem "
          "(normal on HPC: same shared home/scratch, nothing to copy) before running scripts 13-15 there.")


if __name__ == "__main__":
    main()
