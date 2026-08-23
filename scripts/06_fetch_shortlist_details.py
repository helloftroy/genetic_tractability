"""Fetch full Europe PMC records (title/abstract/OA status/pmcid) for every
paper in extraction_shortlist.csv, so the manual extraction pass (done by
the analyst/LLM reading the text, per spec section 6: do not paraphrase
evidence with an LLM) has abstract text to work from without re-querying
one paper at a time.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, cached_get_json, parse_epmc_record, read_csv_dicts, EPMC_BASE
import urllib.parse


def fetch_record(doi: str, pmid: str, title: str) -> dict | None:
    if doi:
        query = f'DOI:"{doi}"'
    elif pmid:
        query = f'EXT_ID:{pmid} AND SRC:MED'
    else:
        query = f'TITLE:"{title}"'
    url = f"{EPMC_BASE}/search?query={urllib.parse.quote(query)}&format=json&resultType=core&pageSize=1"
    data = cached_get_json(url, "epmc")
    if not data:
        return None
    results = data.get("resultList", {}).get("result", [])
    if not results:
        return None
    return parse_epmc_record(results[0])


def main() -> None:
    shortlist = read_csv_dicts(DATA_DIR / "extraction_shortlist.csv")
    out = []
    for row in shortlist:
        rec = fetch_record(row.get("doi", ""), row.get("pmid", ""), row.get("title", ""))
        if not rec:
            rec = {"title": row.get("title", ""), "abstract": "", "is_open_access": False, "pmcid": ""}
        out.append({
            "paper_id": row["paper_id"],
            "score": row["score"],
            "discovery_route": row["discovery_route"],
            "title": rec.get("title") or row.get("title", ""),
            "doi": rec.get("doi") or row.get("doi", ""),
            "pmid": rec.get("pmid") or row.get("pmid", ""),
            "pmcid": rec.get("pmcid", ""),
            "year": rec.get("year") or row.get("year", ""),
            "journal": rec.get("journal", ""),
            "is_open_access": rec.get("is_open_access", False),
            "abstract": rec.get("abstract", ""),
        })

    out_path = DATA_DIR / "extraction_shortlist_details.json"
    out_path.write_text(json.dumps(out, indent=2))
    n_abstract = sum(1 for r in out if r["abstract"])
    n_oa = sum(1 for r in out if r["is_open_access"])
    print(f"Fetched details for {len(out)} papers ({n_abstract} with abstract text, {n_oa} open access)")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
