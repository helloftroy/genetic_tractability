# -*- coding: utf-8 -*-
"""Splits paper text (JATS XML full text, or a bare abstract) into
(section_name, paragraph_index, sentence_text) tuples for keyword tagging.

Deliberately simple: a naive sentence splitter and a flat walk over JATS
<sec>/<title>/<p> in document order. This doesn't need to be a real NLP
sentence tokenizer -- it only has to be good enough that a keyword hit's
surrounding sentence is coherent evidence text.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

_SENTENCE_SPLIT_RX = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])")


def split_sentences(paragraph: str) -> list[str]:
    paragraph = " ".join(paragraph.split())
    if not paragraph:
        return []
    parts = _SENTENCE_SPLIT_RX.split(paragraph)
    return [p.strip() for p in parts if p.strip()]


def _text(el: ET.Element) -> str:
    return " ".join("".join(el.itertext()).split())


def sentences_from_abstract(abstract_html: str) -> list[tuple[str, int, str]]:
    """Abstract text sometimes carries light HTML (h4 headers, <p>). Strip
    tags, then split into sentences under section_name='abstract'."""
    import html as _html
    text = _html.unescape(abstract_html or "")
    text = re.sub(r"<h4>([^<]*)</h4>", r". \1: ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    out = []
    for i, sent in enumerate(split_sentences(text)):
        out.append(("abstract", 0, sent))
    return out


def sentences_from_jats(xml_text: str) -> list[tuple[str, int, str]]:
    """Walk the JATS <body> in document order; each <p> becomes one or more
    (nearest_preceding_section_title, paragraph_index, sentence) tuples."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    body = root.find(".//body")
    if body is None:
        return []

    out = []
    para_index = 0
    current_title = "body"

    def walk(el: ET.Element) -> None:
        nonlocal para_index, current_title
        for child in el:
            tag = child.tag
            if tag == "title" and el.tag == "sec":
                current_title = _text(child) or current_title
                continue
            if tag == "p":
                text = _text(child)
                if text:
                    para_index += 1
                    for sent in split_sentences(text):
                        out.append((current_title, para_index, sent))
                continue
            if tag in ("table-wrap", "fig", "disp-formula", "supplementary-material"):
                continue  # tables handled separately (script 12); figures/formulas have no prose
            walk(child)

    walk(body)
    return out


def sentences_from_pdf_text(pdf_text: str) -> list[tuple[str, int, str]]:
    """PDF-extracted text (pypdf) has no section markup at all -- pypdf
    concatenates a page's text with no heading/paragraph structure
    preserved, so section_name is a flat 'fulltext_pdf' marker rather
    than a real heading (unlike sentences_from_jats, which gets real
    section titles from the XML structure). Paragraph boundaries are
    approximated from blank lines, which pypdf does sometimes preserve."""
    out = []
    para_index = 0
    for para in re.split(r"\n\s*\n", pdf_text or ""):
        text = " ".join(para.split())
        if not text:
            continue
        para_index += 1
        for sent in split_sentences(text):
            out.append(("fulltext_pdf", para_index, sent))
    return out


def sentences_for_paper(
    abstract: str, jats_xml: str | None, pdf_text: str | None = None
) -> tuple[list[tuple[str, int, str]], str]:
    """Prefers real structured full text (JATS XML, real section titles),
    then a PDF-extracted fallback (OpenAlex open-access PDF -- catches
    papers genuinely open access elsewhere but never deposited in PMC,
    flat text but still far richer than an abstract), then the abstract.
    Returns (sentences, source) where source is 'fulltext', 'fulltext_pdf',
    or 'abstract'."""
    if jats_xml:
        sents = sentences_from_jats(jats_xml)
        if sents:
            return sents, "fulltext"
    if pdf_text:
        sents = sentences_from_pdf_text(pdf_text)
        if sents:
            return sents, "fulltext_pdf"
    return sentences_from_abstract(abstract), "abstract"
