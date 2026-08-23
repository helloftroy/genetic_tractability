# -*- coding: utf-8 -*-
"""Keyword lexicon for deterministic (non-LLM) span-finding in paper text.

Straight from the user-supplied keyword table. Regex-compiled once at
import time. Deliberately NOT trying to be exhaustive NLP -- the point is
cheap, auditable candidate-sentence selection; qwen only ever sees the
sentences these patterns flag, never the raw paper text.
"""
from __future__ import annotations

import re

MANIPULATION_TERMS = [
    "transform", "electroporat", "conjugat", "mating", "mobiliz", "transduction",
    "transfect", "natural competence", "naturally competent", "natural transformation",
    "competence induction", "plasmid introduction", "plasmid transfer", "DNA uptake",
    "gene transfer", "genetic manipulation", "genetic modification", "genetic engineering",
    "genome editing", "gene editing", "allelic exchange", "homologous recombination",
    "recombineering", "marker exchange", "gene replacement", "gene deletion", "gene knockout",
    "gene disruption", "gene insertion", "gene integration", "knock-in", "transposon mutagenesis",
    "transposon insertion", "CRISPR", "Cas9", "Cas12a", "Cpf1", "CRISPRi", "CRISPR interference",
    "heterologous expression", "reporter expression", "plasmid maintenance", "shuttle vector",
    "suicide vector", "replicative plasmid",
]

STRAIN_TERMS = [
    "strain", "isolate", "type strain", "wild type", "wild-type", "WT", " sp.", "subsp.",
]
CULTURE_COLLECTION_PREFIXES = [
    "DSM", "DSMZ", "ATCC", "JCM", "NBRC", "NCIMB", "NCTC", "KCTC", "CCUG", "LMG",
    "CGMCC", "CIP", "CECT", "VKM", "BCCM", "CBS", "CCAP", "SAG", "UTEX",
]

ACCESSION_TERMS = [
    "accession", "accession number", "GenBank", "RefSeq", "NCBI", "assembly",
    "genome accession", "BioProject", "BioSample", "ENA", "DDBJ",
]
# Real accession-number regexes (these can be pulled with zero LLM involvement).
ACCESSION_PATTERNS = {
    "gcf": re.compile(r"\bGCF_\d{9}\.\d+\b"),
    "gca": re.compile(r"\bGCA_\d{9}\.\d+\b"),
    "refseq_nc": re.compile(r"\bNC_\d{6,}\.\d+\b"),
    "refseq_nz": re.compile(r"\bNZ_[A-Z]{2,4}\d{6,}\.\d+\b"),
    "genbank_cp": re.compile(r"\bCP\d{6}\.\d+\b"),
    "wgs_master": re.compile(r"\b[A-Z]{2,4}\d{8,9}\b"),  # e.g. JAA/JA-style WGS master prefixes
    "biosample": re.compile(r"\bSAMN\d{8,9}\b"),
    "bioproject": re.compile(r"\bPRJNA\d{4,9}\b|\bPRJEB\d{4,9}\b|\bPRJDB\d{4,9}\b"),
}

SUCCESS_TERMS = [
    "successfully transformed", "successfully introduced", "successfully transferred",
    "successfully conjugated", "successfully integrated", "successful transformation",
    "transformants were obtained", "transformants obtained", "transconjugants were obtained",
    "transconjugants obtained", "colonies were obtained", "recombinants were obtained",
    "mutants were obtained", "stable transformants", "stable integration", "confirmed by PCR",
    "verified by PCR", "confirmed by sequencing", "editing efficiency", "transformation efficiency",
    "conjugation efficiency", "transfer frequency", "mutation efficiency", "integration efficiency",
    "yielded transformants", "resulted in transformants", "enabled transformation",
    "allowed transformation",
]

FAILURE_TERMS = [
    "failed to transform", "unable to transform", "could not transform",
    "could not be transformed", "no transformants", "no transconjugants", "no colonies",
    "no recombinant colonies", "no mutants", "unsuccessful", "transformation failed",
    "electroporation failed", "conjugation failed", "editing failed",
    "no detectable transformation", "below detection limit", "recalcitrant to transformation",
    "refractory to transformation", "resistant to transformation", "unable to introduce",
    "could not introduce", "failed to introduce", "plasmid could not replicate",
    "plasmid did not replicate", "plasmid was unstable", "unstable plasmid", "Cas9 toxicity",
    "Cas9 was toxic", "lethal Cas9", "failed integration", "no integration", "no viable colonies",
]

WILD_TYPE_TERMS = [
    "wild type", "wild-type", "WT", "parental strain", "parent strain", "parental isolate",
    "original isolate", "unmodified strain", "native strain", "naturally occurring",
    "environmental isolate", "clinical isolate", "type strain", "isolated from",
]

NOT_WILD_TYPE_TERMS = [
    "mutant", "derivative", "engineered strain", "recombinant strain", "knockout",
    "deletion mutant", "Δ", "delta", "disruption mutant", "adapted strain",
    "laboratory-evolved", "domesticated strain", "restriction-deficient",
    "methylation-deficient", "recA mutant", "ΔrecA", "Δhsd", "Δrestriction",
    "genome-reduced", "auxotroph", "competence-induced mutant", "modified strain",
]

ISOLATION_SOURCE_TERMS = [
    "isolated from", "isolate from", "was isolated from", "originally isolated from",
    "obtained from", "recovered from", "collected from", "sampled from", "originated from",
    "derived from", "source of isolation", "isolation source", "habitat",
    "environmental origin", "sampling site", "collection site", "host", "sediment", "seawater",
    "marine sediment", "soil", "freshwater", "wastewater", "sludge", "rhizosphere", "gut",
    "intestine", "skin", "sponge", "coral", "algae", "biofilm", "hydrothermal vent",
    "salt marsh", "estuary", "coastal water", "deep sea", "brine", "saltern",
]

CATEGORIES = {
    "manipulation": MANIPULATION_TERMS,
    "strain": STRAIN_TERMS,
    "accession": ACCESSION_TERMS,
    "success": SUCCESS_TERMS,
    "failure": FAILURE_TERMS,
    "wild_type": WILD_TYPE_TERMS,
    "not_wild_type": NOT_WILD_TYPE_TERMS,
    "isolation_source": ISOLATION_SOURCE_TERMS,
}


def _compile_term(term: str) -> re.Pattern:
    # Trailing "*" in the user's list means a stem match (transform* -> transform/transformed/...).
    if term.endswith("*"):
        return re.compile(re.escape(term[:-1]), re.IGNORECASE)
    return re.compile(re.escape(term), re.IGNORECASE)


COMPILED_CATEGORIES = {cat: [(t, _compile_term(t)) for t in terms] for cat, terms in CATEGORIES.items()}


def tag_sentence(sentence: str) -> dict:
    """Return {category: [matched terms]} for every category with a hit."""
    hits = {}
    for cat, patterns in COMPILED_CATEGORIES.items():
        matched = [term for term, rx in patterns if rx.search(sentence)]
        if matched:
            hits[cat] = matched
    return hits


def find_culture_collection_strains(text: str) -> list[str]:
    prefix_alt = "|".join(re.escape(p) for p in CULTURE_COLLECTION_PREFIXES)
    pattern = re.compile(rf"\b({prefix_alt})\s?-?\s?\d{{2,6}}(?:\.\d+)?\b")
    return sorted(set(m.group(0) for m in pattern.finditer(text)))


def find_accessions(text: str) -> dict[str, list[str]]:
    found = {}
    for kind, rx in ACCESSION_PATTERNS.items():
        matches = sorted(set(rx.findall(text)))
        if matches:
            found[kind] = matches
    return found
