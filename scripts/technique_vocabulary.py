# -*- coding: utf-8 -*-
"""Controlled technique vocabulary for the v2 pipeline (spec sections 8-10).

Distinct from keyword_lexicon.py (the v1 pipeline's simpler category
list, still used unmodified by scripts 01-21): this is organized by
technique_normalized -> raw phrase variants, so the SAME list drives both
query construction (discovery_v2.py) and passage tagging (screen_v2.py)
without duplicating the phrase list in two places.

TECHNIQUE_CATEGORIES intentionally covers the exact vocabulary the spec
gave, grouped the same way. raw_technique_text is preserved separately
from technique_normalized at extraction time (attempt_db.py) -- an
unusual method that matches no category here should never be forced into
one; "other" plus the raw text is always a valid outcome.
"""
from __future__ import annotations

TECHNIQUE_CATEGORIES: dict[str, list[str]] = {
    # DNA introduction
    "transformation": [
        "transformation", "genetic transformation", "electrotransformation",
        "electroporation", "chemical transformation", "heat-shock transformation",
        "heat shock transformation",
    ],
    # Conjugation
    "conjugation": [
        "conjugation", "conjugal transfer", "conjugative transfer", "biparental mating",
        "triparental mating", "tri-parental mating", "mating",
    ],
    # Natural competence
    "natural_competence": [
        "natural transformation", "natural competence", "competence induction",
    ],
    # Plasmid introduction/maintenance
    "plasmid_introduction": [
        "plasmid introduction", "plasmid transfer", "plasmid transformation",
        "episomal plasmid", "shuttle vector", "replicative plasmid",
    ],
    # Recombination / knockouts
    "allelic_exchange": [
        "allelic exchange", "homologous recombination", "single crossover", "double crossover",
        "suicide vector", "suicide plasmid", "counterselection", "sacB", "gene deletion",
        "gene knockout", "gene replacement", "markerless deletion",
    ],
    # Recombineering
    "recombineering": [
        "recombineering", "lambda red", "red recombination", "recet",
    ],
    # CRISPR
    "crispr": [
        "crispr", "crispr-cas", "cas9", "cas12a", "cpf1", "base editing", "prime editing",
        "crispr interference", "crispri",
    ],
    # Transposons
    "transposon_mutagenesis": [
        "transposon mutagenesis", "transposon insertion", "tn5", "mariner", "mini-tn",
    ],
    # Expression / reporters
    "heterologous_expression": [
        "heterologous expression", "reporter expression", "gfp expression",
        "fluorescent reporter", "promoter reporter", "gene expression vector",
    ],
}

# Flat list of every raw phrase, for building the "generic technique" OR-group
# (spec section 7's example query) without repeating the category dict.
ALL_TECHNIQUE_PHRASES: list[str] = sorted({p for phrases in TECHNIQUE_CATEGORIES.values() for p in phrases})


def normalize_technique(raw_text: str) -> str:
    """Best-effort deterministic mapping from a raw phrase to a category
    name, for pre-LLM scoring/query construction. The LLM extraction step
    makes the real per-attempt technique_normalized call with actual
    context (screen_v2.py's score is a triage aid, not the final label)."""
    text = raw_text.lower()
    for category, phrases in TECHNIQUE_CATEGORIES.items():
        for phrase in phrases:
            if phrase in text:
                return category
    return "other"


# ---------------------------------------------------------------------------
# Discovery strategy C: generic technique-first phrases (spec section 9) --
# independent of any known organism, catches organisms reviews never
# mentioned. Includes "novelty" phrasing, which disproportionately precedes
# a description of failed attempts before optimization.
# ---------------------------------------------------------------------------
GENERIC_DISCOVERY_PHRASES: list[str] = [
    "development of genetic tools", "genetic tools for", "genetic manipulation of",
    "genetic system for", "genetic tractability", "genetically tractable",
    "genetically intractable", "genetically recalcitrant",
    "transformation of", "electroporation of", "conjugation in", "allelic exchange in",
]

NOVELTY_PHRASES: list[str] = [
    "first genetic system", "first genetic tools", "first transformation",
    "first successful transformation", "lack of genetic tools", "no genetic tools available",
]

# ---------------------------------------------------------------------------
# Discovery strategy D: explicit failure-language phrases (spec section 10).
# ---------------------------------------------------------------------------
FAILURE_DISCOVERY_PHRASES: list[str] = [
    "no transformants", "no colonies", "no recombinants", "no mutants",
    "failed to transform", "failed transformation", "unsuccessful transformation",
    "could not be transformed", "could not transform", "unable to transform",
    "not transformable", "transformation was unsuccessful", "electroporation was unsuccessful",
    "unable to introduce", "failed to introduce",
    "plasmid could not be introduced", "plasmid did not replicate", "plasmid failed to replicate",
    "plasmid was unstable", "unable to maintain plasmid", "plasmid loss",
    "no integration", "no homologous recombination",
    "no colonies were obtained", "no colonies were recovered", "no transformants were recovered",
    "no mutants were obtained", "below detection", "no detectable transformants",
    "low transformation efficiency", "poor transformation efficiency",
]

# ---------------------------------------------------------------------------
# Success-language phrases -- used for passage scoring (screen_v2.py), same
# role as keyword_lexicon.py's SUCCESS_TERMS but kept local here so this
# module is a self-contained single source of truth for the v2 pipeline.
# ---------------------------------------------------------------------------
SUCCESS_DISCOVERY_PHRASES: list[str] = [
    "transformants were obtained", "transformants obtained", "successfully transformed",
    "plasmid introduced and maintained", "targeted deletion confirmed", "integration confirmed",
    "reporter expressed", "colonies were obtained", "recombinants were obtained",
    "mutants were obtained", "stable transformants",
]

# ---------------------------------------------------------------------------
# Failure-reason vocabulary (spec section 24) -- controlled values plus raw
# text is always retained separately.
# ---------------------------------------------------------------------------
FAILURE_REASON_VALUES: list[str] = [
    "restriction-modification barrier", "DNA methylation", "plasmid incompatibility",
    "plasmid failed to replicate", "poor DNA uptake", "cell death",
    "antibiotic selection problem", "low recombination", "Cas toxicity", "guide toxicity",
    "vector instability", "unknown",
]

# ---------------------------------------------------------------------------
# Wild-type status vocabulary (spec section 20).
# ---------------------------------------------------------------------------
WILD_TYPE_STATUS_VALUES: list[str] = [
    "explicit_wild_type", "unmodified_parental_strain", "engineered_background",
    "laboratory_adapted_or_mutant", "unclear",
]

OUTCOME_VALUES: list[str] = ["success", "partial_success", "failure", "mixed", "unclear"]


def build_organism_technique_query(organism: str, technique_phrases: list[str] | None = None) -> str:
    """One OR-grouped PubMed query per organism (spec section 7) instead
    of one HTTP call per organism x phrase pair."""
    phrases = technique_phrases or ALL_TECHNIQUE_PHRASES
    or_group = " OR ".join(f'"{p}"' if " " in p else p for p in phrases)
    return f'"{organism}" AND ({or_group})'
