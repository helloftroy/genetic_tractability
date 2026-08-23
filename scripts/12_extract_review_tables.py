# -*- coding: utf-8 -*-
"""Pull candidate primary papers out of review-paper tables (spec 3A step 2).

Reviews summarizing genetic-manipulation methods commonly carry a table
like "Host | Endonuclease | ... | Reference", one row per organism/method
combination, each row citing its source paper. That is a far higher-
precision candidate source than a review's full reference list (script 04
pulls hundreds of background-citation refs per review; a table row is
specifically "this organism was manipulated this way, see this paper").

For every open-access review with full text, this walks every
<table-wrap>, and for each row that cites at least one bibliography entry
(<xref ref-type="bibr">): resolves the cited reference's DOI/PMID/title
from the article's own <ref-list>, adds it to candidate_papers.csv
(discovery_route=review_reference, tagged as table-derived in notes), and
records the row in review_table_extractions.csv with an organism guess
(taken from <italic> markup, which in these tables reliably wraps the
host-organism name) so step 3's LLM extraction pass has a pre-attached
hint to cross-check against, not just a blind PDF/abstract dump.
"""
from __future__ import annotations

import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from candidate_store import CandidateStore
from common import DATA_DIR, epmc_fulltext_xml, normalize_title, read_csv_dicts, write_csv_dicts

TABLE_FIELDNAMES = [
    "review_paper_id", "review_title", "table_label", "table_caption",
    "row_index", "row_text", "organism_guess",
    "cited_doi", "cited_pmid", "cited_title", "cited_year", "cited_source",
    "matched_candidate_paper_id",
]


def cell_text(cell: ET.Element) -> str:
    return " ".join("".join(cell.itertext()).split())


def row_cells(tr: ET.Element) -> list[ET.Element]:
    return tr.findall("./td") + tr.findall("./th")


def build_ref_index(root: ET.Element) -> dict[str, dict]:
    index = {}
    for ref in root.findall(".//ref"):
        rid = ref.get("id")
        if not rid:
            continue
        title_el = ref.find(".//article-title")
        title = cell_text(title_el) if title_el is not None else ""

        doi = ""
        pmid = ""
        for pub_id in ref.findall(".//pub-id"):
            t = pub_id.get("pub-id-type", "")
            if t == "doi":
                doi = (pub_id.text or "").strip()
            elif t == "pmid":
                pmid = (pub_id.text or "").strip()

        # Some journals (e.g. Elsevier/Trends) don't use <pub-id> at all --
        # identifiers live in <ext-link ext-link-type="doi/pmid"
        # xlink:href="...">, and the whole citation is one opaque
        # <named-content content-type="citation-string"> blob with no
        # <article-title>. ElementTree exposes the namespaced xlink:href
        # attribute as "{http://www.w3.org/1999/xlink}href" regardless of
        # whatever prefix the source document declared, so match on the
        # attribute's local name rather than a hardcoded prefix.
        if not doi or not pmid:
            for ext_link in ref.findall(".//ext-link"):
                link_type = ext_link.get("ext-link-type", "")
                href = next((v for k, v in ext_link.attrib.items() if k.endswith("}href") or k == "href"), "")
                if link_type == "doi" and not doi and href:
                    doi = href.strip()
                elif link_type == "pmid" and not pmid and href:
                    pmid = href.strip()

        if not title:
            # A google-scholar ext-link's href often carries the real title
            # as a "title=" query param -- try that before giving up.
            for ext_link in ref.findall(".//ext-link"):
                if ext_link.get("ext-link-type") == "google-scholar":
                    href = next((v for k, v in ext_link.attrib.items() if k.endswith("}href") or k == "href"), "")
                    m = re.search(r"[?&]title=([^&]+)", href)
                    if m:
                        title = urllib.parse.unquote_plus(m.group(1)).strip()
                        break
        if not title:
            # Books/chapters/software sometimes use <source> as the citable title instead.
            source_el = ref.find(".//source")
            title = cell_text(source_el) if source_el is not None else ""
        if not title and not doi and not pmid:
            # Last resort: try to pull a bare DOI out of the raw citation
            # text even with no structured markup at all, so at least DOI
            # resolution still works even when nothing else parsed.
            m = re.search(r"\b10\.\d{4,9}/\S+", cell_text(ref))
            if m:
                doi = m.group(0).rstrip(".,;)")

        year_el = ref.find(".//year")
        source_el = ref.find(".//source")
        index[rid] = {
            "title": title,  # deliberately NOT falling back to raw citation text -- a garbled
            "doi": doi,      # "title" would poison downstream title-based search/dedup; better
            "pmid": pmid,    # to leave it blank and let doi/pmid carry identification instead.
            "year": cell_text(year_el) if year_el is not None else "",
            "source": cell_text(source_el) if source_el is not None else "",
        }
    return index


def organism_guess_for_row(cells: list[ET.Element]) -> str:
    if cells:
        italics = cells[0].findall(".//italic")
        text = " ".join(cell_text(i) for i in italics if cell_text(i))
        if text:
            return text
    for cell in cells:
        italics = cell.findall(".//italic")
        text = " ".join(cell_text(i) for i in italics if cell_text(i))
        if text:
            return text
    return ""


def extract_tables(paper_id: str, title: str, xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    ref_index = build_ref_index(root)
    rows_out = []

    for table in root.findall(".//table-wrap"):
        label_el = table.find("label")
        caption_el = table.find("caption")
        label = cell_text(label_el) if label_el is not None else ""
        caption = cell_text(caption_el) if caption_el is not None else ""

        for i, tr in enumerate(table.findall(".//tr")):
            cells = row_cells(tr)
            if not cells:
                continue
            bibr_rids = [x.get("rid") for x in tr.findall('.//xref[@ref-type="bibr"]') if x.get("rid")]
            if not bibr_rids:
                continue  # header/no-citation rows aren't candidate-paper sources
            row_text = " | ".join(cell_text(c) for c in cells)
            organism = organism_guess_for_row(cells)
            for rid in bibr_rids:
                ref = ref_index.get(rid)
                if not ref or not (ref["doi"] or ref["pmid"] or ref["title"]):
                    continue
                rows_out.append({
                    "review_paper_id": paper_id,
                    "review_title": title,
                    "table_label": label,
                    "table_caption": caption,
                    "row_index": i,
                    "row_text": row_text,
                    "organism_guess": organism,
                    "cited_doi": ref["doi"],
                    "cited_pmid": ref["pmid"],
                    "cited_title": ref["title"],
                    "cited_year": ref["year"],
                    "cited_source": ref["source"],
                    "matched_candidate_paper_id": "",
                })
    return rows_out


def main() -> None:
    store = CandidateStore()
    papers = read_csv_dicts(DATA_DIR / "candidate_papers.csv")
    reviews = [
        p for p in papers
        if p.get("is_review") == "True" and p.get("full_text_available") == "True" and p.get("pmcid")
    ]

    all_rows = []
    n_with_tables = 0
    n_fetch_failed = 0

    for i, review in enumerate(reviews, start=1):
        xml_text = epmc_fulltext_xml(review["pmcid"])
        if not xml_text:
            n_fetch_failed += 1
            continue
        rows = extract_tables(review["paper_id"], review["title"], xml_text)
        if rows:
            n_with_tables += 1
        for row in rows:
            paper_id = store.add(
                title=row["cited_title"],
                doi=row["cited_doi"],
                pmid=row["cited_pmid"],
                year=row["cited_year"],
                journal=row["cited_source"],
                source_database="europe_pmc_table_reference",
                discovery_route="review_reference",
                discovery_query=f"table extraction: {review['title'][:70]} / {row['table_label']}",
                review_seed_doi=review.get("doi", "") or review["paper_id"],
                processing_status="discovered",
                notes=f"From table '{row['table_label']}' ({row['table_caption'][:80]}); organism_guess={row['organism_guess'] or 'n/a'}",
            )
            row["matched_candidate_paper_id"] = paper_id
            all_rows.append(row)
        if i % 25 == 0:
            print(f"  ...processed {i}/{len(reviews)} OA reviews, {len(all_rows)} table rows so far")

    write_csv_dicts(DATA_DIR / "review_table_extractions.csv", all_rows, TABLE_FIELDNAMES)
    store.save()

    print(f"OA reviews checked: {len(reviews)} (fetch failed: {n_fetch_failed})")
    print(f"Reviews with at least one usable table: {n_with_tables}")
    print(f"Table rows with a resolvable citation: {len(all_rows)}")
    print(f"Unique cited papers added/enriched: {len(set(r['matched_candidate_paper_id'] for r in all_rows))}")
    print(f"Wrote {DATA_DIR / 'review_table_extractions.csv'}")


if __name__ == "__main__":
    main()
