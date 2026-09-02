#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phased CLI orchestrator for the v2 (NCBI/PubMed/PMC) genetic-engineering
attempt discovery pipeline (spec sections 32-34).

Literature infrastructure is NCBI E-utilities (ESearch/ESummary/EFetch/
ELink, see ncbi_eutils.py) and PMC BioC (see pmc_bioc.py) ONLY.

OpenAlex is deliberately NOT used anywhere in this pipeline (spec section
39/rule) -- disabled entirely, not just defaulted off, because repeated
searches got rate-limited/blocked too easily in practice. This is a
DIFFERENT policy from the v1 pipeline (scripts 01-21), which does use an
OpenAlex open-access-PDF fallback deliberately and separately -- the two
pipelines are independent, this rule applies only to this one. If a paper
can't be resolved through NCBI/PMC here, it stays unresolved
(fulltext_status=unavailable_from_pmc) rather than silently falling back
to OpenAlex.

Phases (each independently resumable -- see attempt_db.py's
processing_status column, spec section 35):
  pubmed-search  -- discovery strategies A-D (discovery_v2.py)
  citations      -- forward/backward citation expansion (citation_expansion_v2.py)
  fulltext       -- (folded into `screen`, which fetches full text as needed)
  screen         -- deterministic scoring + passage extraction (screen_v2.py)
  extract        -- LLM extraction into engineering_attempts (extract_v2.py)
  reports        -- CSV exports + summary (reports_v2.py)
  all            -- every phase above, in order

Usage:
  python3 run_engineering_discovery.py --phase all --max-papers 25   # cheap test run first (spec section 34)
  python3 run_engineering_discovery.py --phase pubmed-search
  python3 run_engineering_discovery.py --phase citations --citation-depth 1
  python3 run_engineering_discovery.py --phase screen
  python3 run_engineering_discovery.py --phase extract --no-llm   # dry run: screens only, skips the LLM call
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from attempt_db import init_db

PHASES = ["pubmed-search", "citations", "fulltext", "screen", "extract", "reports", "all"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--phase", choices=PHASES, required=True)
    parser.add_argument("--resume", action="store_true", help="default behavior anyway (every phase only "
                         "processes what's not already done) -- accepted for CLI compatibility with the spec")
    parser.add_argument("--refresh", action="store_true", help="not yet implemented: would force re-checking "
                         "already-processed papers rather than skipping them")
    parser.add_argument("--max-papers", type=int, default=None, help="cap on papers/queries processed this run "
                         "(spec section 34's cheap test mode: --max-papers 25)")
    parser.add_argument("--organism-file", type=str, default=None, help="extra organisms, one per line, "
                         "merged into the auto-built organism list (spec section 7)")
    parser.add_argument("--citation-depth", type=int, default=1, help="citation expansion hops (spec section 13: "
                         "default 1, do not recursively crawl the whole graph)")
    parser.add_argument("--no-llm", action="store_true", help="skip the extract phase's LLM call entirely "
                         "(screening/reports still run)")
    args = parser.parse_args()

    if args.refresh:
        print("--refresh is not yet implemented (every phase currently only processes what's not already "
              "done -- there's no way yet to force re-checking something already screened/extracted).",
              file=sys.stderr)

    init_db()
    phases_to_run = PHASES[:-1] if args.phase == "all" else [args.phase]

    for phase in phases_to_run:
        print(f"\n{'=' * 72}\nPHASE: {phase}\n{'=' * 72}")
        if phase == "pubmed-search":
            import discovery_v2
            discovery_v2.run_all(organism_file=args.organism_file, max_papers=args.max_papers)
        elif phase == "citations":
            import citation_expansion_v2
            citation_expansion_v2.run(depth=args.citation_depth, max_seeds=args.max_papers)
        elif phase == "fulltext":
            print("(folded into 'screen' -- full text is fetched on demand per paper there, not a separate pass)")
        elif phase == "screen":
            import screen_v2
            screen_v2.run(max_papers=args.max_papers)
        elif phase == "extract":
            if args.no_llm:
                print("--no-llm set: skipping LLM extraction (screening already ran in the 'screen' phase).")
            else:
                import extract_v2
                extract_v2.run(max_papers=args.max_papers)
        elif phase == "reports":
            import reports_v2
            reports_v2.run()

    print("\nDone.")


if __name__ == "__main__":
    main()
