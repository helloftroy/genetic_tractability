# -*- coding: utf-8 -*-
"""Heals "forced maybe" triage rows -- papers where script 13's abstract
lookup failed (not genuine LLM ambiguity) and got a placeholder
decision="maybe"/abstract_available="False" recorded instead of being
silently dropped (per spec: no evidence is not a negative result).

The problem: select_triage_batch() permanently excludes any paper_id
already present in abstract_triage.csv, and run_prefetch.sbatch uses that
same exclusion -- so once a paper lands in this state, NOTHING ever
retries its lookup again. Confirmed live: after an earlier period where
run_extraction.sbatch's GPU node (no internet) was attempting live
lookups that could never succeed, essentially 100% of one user's
"triaged yes/maybe, awaiting keyword-span extraction" backlog turned out
to be these placeholder rows, most of them still permanently uncached.

This script must run somewhere WITH internet access (the discovery/
service partition, i.e. as part of or alongside run_prefetch.sbatch) --
it makes real epmc_lookup_record() calls, not cache-only checks. For
each forced-maybe row, retries the lookup; if an abstract is found now,
REMOVES the row from abstract_triage.csv entirely (rather than trying to
patch its decision in place) so a subsequent run of script 13 picks the
paper up again for a genuine triage decision, on real content this time.
Rows that still fail are left alone -- either a transient issue that
will resolve on a later retry, or a paper Europe PMC genuinely has no
abstract for.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, epmc_lookup_record, locked_merge_write_csv, read_csv_dicts

TRIAGE_FIELDNAMES = ["paper_id", "title", "decision", "reason", "abstract_available"]
TRIAGE_PATH = DATA_DIR / "abstract_triage.csv"


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10_000_000
    triage = read_csv_dicts(TRIAGE_PATH)
    papers = {p["paper_id"]: p for p in read_csv_dicts(DATA_DIR / "candidate_papers.csv")}

    forced_maybe_rows = [t for t in triage if t.get("abstract_available") == "False"][:limit]
    print(f"Retrying {len(forced_maybe_rows)} forced-maybe (failed-lookup) rows "
          f"out of {sum(1 for t in triage if t.get('abstract_available') == 'False')} total...")

    healed_ids: set[str] = set()
    healed_since_checkpoint: set[str] = set()
    for i, row in enumerate(forced_maybe_rows, start=1):
        paper = papers.get(row["paper_id"])
        if not paper:
            continue
        rec = epmc_lookup_record(paper.get("doi", ""), paper.get("pmid", ""), paper.get("title", ""))
        if rec and rec.get("abstract"):
            healed_ids.add(row["paper_id"])
            healed_since_checkpoint.add(row["paper_id"])
        if i % 200 == 0:
            print(f"  ...{i}/{len(forced_maybe_rows)} checked, {len(healed_ids)} healed so far", flush=True)
            # Periodic checkpoint (not just at the end) -- re-reads fresh under
            # lock each time (locked_merge_write_csv), so this is safe even if
            # script 13 is concurrently adding new rows to the same file.
            if healed_since_checkpoint:
                locked_merge_write_csv(TRIAGE_PATH, TRIAGE_FIELDNAMES, remove_ids=healed_since_checkpoint)
                healed_since_checkpoint = set()

    if healed_since_checkpoint:
        locked_merge_write_csv(TRIAGE_PATH, TRIAGE_FIELDNAMES, remove_ids=healed_since_checkpoint)

    print(f"Done. {len(healed_ids)} rows healed (removed from abstract_triage.csv -- "
          f"will be genuinely re-triaged by the next run of script 13) and "
          f"{len(forced_maybe_rows) - len(healed_ids)} still not fetchable, left as-is.")


if __name__ == "__main__":
    main()
