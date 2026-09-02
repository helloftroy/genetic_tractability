# -*- coding: utf-8 -*-
"""PMC BioC full-text fetch + section-aware parsing.

Preferred over Europe PMC's JATS fullTextXML for the v2 pipeline: BioC
passages carry an explicit `section_type` infon (TITLE, ABSTRACT, METHODS,
RESULTS, DISCUSSION, SUPPL, ...) per passage already assigned by NCBI, so
Methods/Results/Supplement don't need to be inferred from heading text the
way the v1 pipeline's JATS-title-matching does.

Endpoint confirmed live (double slash after "RESTful" is required -- not a
typo, NCBI's own docs example has it):
  https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful//pmcoa.cgi/BioC_json/{PMCID}/unicode
Rate limit confirmed live: 429 "Maximum 3 requests per second per user" --
this shares common.py's "ncbi_bioc" throttle bucket (same real limit as
E-utilities, since it's the same NCBI backend).

Only covers PMC's OPEN ACCESS subset (pmcoa.cgi) -- a PMCID with no BioC
record is either not open access or not yet processed into BioC; callers
should fall back to abstract-only, matching spec section 5 (retain the
candidate, mark fulltext_status=unavailable_from_pmc, never discard it).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import cached_get_json

BIOC_BASE = "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful//pmcoa.cgi/BioC_json"

# BioC's own section_type vocabulary -> this pipeline's four buckets.
# Everything not explicitly mapped falls into OTHER (still retrievable,
# just not treated as primary Methods/Results/Supplement evidence -- spec
# section 2: Introduction/Discussion are for candidate discovery, not
# primary outcome evidence).
SECTION_BUCKET = {
    "METHODS": "METHODS",
    "RESULTS": "RESULTS",
    "RESULTS_AND_DISCUSSION": "RESULTS",
    "SUPPL": "SUPPLEMENT",
    "SUPPLEMENTARY_MATERIAL": "SUPPLEMENT",
    "ABSTRACT": "ABSTRACT",
    "TITLE": "TITLE",
}


@dataclass
class BiocPassage:
    section_bucket: str   # METHODS / RESULTS / SUPPLEMENT / ABSTRACT / TITLE / OTHER
    section_type_raw: str  # BioC's own infon, unmapped
    paragraph_index: int
    text: str


def fetch_bioc_passages(pmcid: str) -> Optional[list[BiocPassage]]:
    """Fetches and flattens one PMCID's BioC document into an ordered list
    of passages. Returns None if PMC has no BioC record for this PMCID
    (not open access, or not yet processed) -- distinct from an empty
    list, which would mean a genuinely empty document."""
    pmcid_clean = pmcid if pmcid.upper().startswith("PMC") else f"PMC{pmcid}"
    url = f"{BIOC_BASE}/{pmcid_clean}/unicode"
    data = cached_get_json(url, "ncbi_bioc")
    if not data:
        return None

    # BioC_json wraps a list containing one collection; a collection with
    # no documents (NCBI's "[Error]: No result can be found" case, which
    # -- unhelpfully -- returns HTTP 200 with a non-JSON error body, so
    # cached_get_json's own json() parse already fails and returns None
    # for that specific case) means genuinely unavailable.
    try:
        collection = data[0] if isinstance(data, list) else data
        documents = collection.get("documents", [])
    except (AttributeError, IndexError, KeyError):
        return None
    if not documents:
        return None

    passages: list[BiocPassage] = []
    para_index = 0
    for doc in documents:
        for passage in doc.get("passages", []):
            text = (passage.get("text") or "").strip()
            if not text:
                continue
            infons = passage.get("infons", {}) or {}
            section_type_raw = (infons.get("section_type") or infons.get("type") or "").upper()
            bucket = SECTION_BUCKET.get(section_type_raw, "OTHER")
            para_index += 1
            passages.append(BiocPassage(
                section_bucket=bucket, section_type_raw=section_type_raw,
                paragraph_index=para_index, text=text,
            ))
    return passages


def passages_to_dicts(passages: list[BiocPassage]) -> list[dict]:
    return [
        {"section": p.section_bucket, "section_type_raw": p.section_type_raw,
         "paragraph": p.paragraph_index, "text": p.text}
        for p in passages
    ]
