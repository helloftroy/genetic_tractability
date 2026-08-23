# genetic_tractability

A discovery + extraction pipeline for building a training-resource seed set
of **organism/strain + paper + genetic-manipulation attempt + success/failure
evidence + genome accession** records, for a future ML model predicting
bacterial (and archaeal/microbial-eukaryote) engineerability / chassis
potential. Prioritizes bacteria but keeps other domains, keeps failures (not
just successes), and keeps a strict separation between wild-type and
engineered/domesticated starting strains.

Standalone (flat scripts + `requests`, no framework) rather than built on
[`fair_ocean_agent`](https://github.com/helloftroy/FAIRe_Ocean_Agent)'s
ORM/task-queue -- that pipeline's Study/Entity/FAIRe data model is built
around eDNA sample metadata, which doesn't fit this project's flatter
paper -> observation shape. It does reuse that project's local-LLM design
principles (provider-independent OpenAI-compatible client, explicit model
selection, no silent fallback) and its two-stage CPU/GPU cluster split.

## Pipeline stages

**1. Paper discovery** (`scripts/01`-`04`, `12`) -- Europe PMC search across
review-paper topics, broad keyword queries, and failure-phrase queries;
extracts both a review's full reference list and, more precisely, every
table row in a review that cites a source paper (a `Host | Method | ... |
Reference` table row is a far higher-precision candidate than a random
background citation). Everything lands deduplicated (by DOI/PMID/normalized
title) in `data/genetic_tractability/candidate_papers.csv`.

**2. Manual extraction pass** (`scripts/05`-`11`) -- the original hand-curated
validation pass: a scored shortlist, abstract fetch, and a manually-read,
verbatim-evidence extraction into `manipulation_observations.csv`
(`extraction_method` implicitly manual), used as ground truth for comparing
the automated pass below.

**3. Automated extraction pass** (`scripts/13`-`16`) -- keyword-first, LLM-light:

- `13_triage_abstracts.py`: qwen reads *only the abstract* and answers
  yes/no/maybe on "does this describe an actual manipulation attempt".
- `14_extract_keyword_spans.py`: **no LLM.** Fetches full text (or falls
  back to the abstract), tags every sentence against `keyword_lexicon.py`
  (manipulation/strain/accession/success/failure/wild-type terms), and
  regex-extracts real accession numbers and culture-collection strain IDs
  directly. This is the "use keywords to find the right spots, don't rely
  on the LLM for that" design.
- `15_llm_structured_extraction.py`: qwen sees *only* the keyword-flagged
  sentences (never the raw paper) and returns one record per
  organism/strain x technique x outcome. Every `evidence_text` is verified
  as a real verbatim substring of a provided sentence before being
  trusted; unverified ones are kept (never silently dropped) but flagged
  `qc_flags=evidence_unverified`.
- `09_genome_matching.py` (shared with the manual pass, parameterized):
  resolves organism/strain against NCBI assembly -- never assigns a genome
  just because one exists for the species; exact strain match is required
  or it's honestly marked `species_only_match`/`no_genome_found`.

## Local (Mac) quickstart

```bash
cd scripts
pip install requests
python3 01_discover_reviews.py && python3 02_broad_keyword_discovery.py \
  && python3 03_negative_keyword_discovery.py && python3 04_review_reference_extraction.py \
  && python3 12_extract_review_tables.py && python3 11_clean_titles.py

# Automated pass (needs a local Ollama server -- see llm_client.py):
python3 13_triage_abstracts.py 300
python3 14_extract_keyword_spans.py 300
python3 15_llm_structured_extraction.py 300
python3 09_genome_matching.py manipulation_observations_auto.csv genome_matches_auto.csv
python3 16_auto_summary_report.py
```

`llm_client.py` defaults to Ollama (`qwen3:4b-instruct-16k` at
`localhost:11434/v1`) -- confirmed live to work, but slower and less
reliable at picking up real signal than vLLM on a GPU. See `cluster/` for
running the LLM-heavy stages on an HPC GPU node instead.

## Cluster (HPC2/Orion) quickstart

See `cluster/README.md`. Same pipeline, split into four SLURM jobs (two
CPU/internet, one GPU/vLLM/no-internet, one CPU/internet again for genome
matching) because this cluster's GPU nodes have no internet access.

## Output files

All under `data/genetic_tractability/`:

| File | What it is |
|---|---|
| `candidate_papers.csv` | Every paper discovered, deduplicated, with discovery route/query |
| `review_seeds.csv` | Review papers used as discovery seeds |
| `review_table_extractions.csv` | Every review-table row with a resolvable citation (organism guess + cited paper) |
| `manipulation_observations.csv` | Manual-pass observations (ground truth) |
| `manipulation_observations_auto.csv` | Automated-pass observations (qwen + keyword lexicon) |
| `genome_matches.csv` / `genome_matches_auto.csv` | NCBI assembly matches per pass |
| `manual_review.csv` | Papers/observations flagged for human follow-up |
| `abstract_triage.csv` | Per-paper yes/no/maybe triage decisions |
| `keyword_spans_index.csv` | Per-paper counts of keyword-tagged sentences by category |

See each script's module docstring for the full design rationale --
`07_build_observations.py` and `12_extract_review_tables.py` in particular
document real bugs found and fixed during development (garbled reference
titles from non-standard JATS citation formats, NCBI esearch's
strain-in-query quirk, HTML-entity-laden titles).
