# Running the v2 (NCBI/PubMed/PMC) pipeline on HPC2

This is a SEPARATE pipeline from the one documented in `cluster/README.md`
(the v1, Europe PMC-based system, `scripts/01`-`21`). The v2 pipeline
(`scripts/run_engineering_discovery.py`) discovers papers via NCBI
E-utilities and PMC BioC instead, extracts one row per organism/strain x
technique x outcome ATTEMPT (not one row per paper), and stores everything
in a SQLite database (`data/genetic_tractability/tractability.db`) instead
of CSVs. **OpenAlex is never used anywhere in this pipeline** -- disabled
entirely by design (repeated OpenAlex searches proved too easy to get
rate-limited/blocked), not just defaulted off. The v1 pipeline's own
OpenAlex open-access-PDF fallback is unrelated and unaffected.

## Why three jobs, not two

Same reasoning as the v1 split (`cluster/README.md`'s "why four jobs"),
but actually simpler here: `extract_v2.py` (the LLM stage) only ever reads
local `chunks_v2/*.json` files and writes to the local SQLite DB -- it
makes **zero network calls**, by design. So there's no CACHE_ONLY/prefetch-
matching dance needed for the GPU stage the way v1's `run_extraction.sbatch`
needs one; screening (which fetches PMC full text) and extraction (LLM)
are cleanly separated into their own jobs with no shared-cache-timing risk.

1. **`run_v2_discovery.sbatch`** (CPU, `service`, internet) -- discovery
   strategies A-D (review-derived seeds, organism x technique search,
   generic technique-first search, failure-language search) plus
   citation expansion (forward/backward, via NCBI ELink). Populates the
   `papers` table.
2. **`run_v2_screen.sbatch`** (CPU, `service`, internet) -- fetches PMC
   BioC full text where available, deterministically scores every
   candidate, and writes `chunks_v2/<paper_id>.json` for anything that
   scores relevant. This is the only stage that touches the network for
   full text.
3. **`run_v2_extract.sbatch`** (GPU, `gpu-a100`, vLLM, **no internet
   needed**) -- LLM extraction into `engineering_attempts`, then generates
   `reports/*.csv`.

## One-time setup

Same environment as the v1 pipeline (`cluster/README.md`'s setup) -- no
separate env needed, `run_engineering_discovery.py` uses the same
`requests`/`pypdf`/`vllm` stack. Just make sure `NCBI_EMAIL` (and
optionally `NCBI_API_KEY`, which raises the E-utilities rate limit from
3 req/s to 10 req/s) are set:

```bash
export NCBI_EMAIL="you@example.org"
export NCBI_API_KEY="..."   # optional but meaningfully faster -- get one free at
                             # https://www.ncbi.nlm.nih.gov/account/settings/
```

Add these to your shell profile or `cluster/env_activate.sh` (regenerated
by `setup_env.sh`, so re-exporting them each session is simplest) so
they're set for every job.

## Cheap test run first (spec section 34)

Before a large crawl, validate the whole pipeline end to end on a small
batch:

```bash
cd scripts
python3 run_engineering_discovery.py --phase all --max-papers 25
```

This runs entirely on a login/interactive node (no GPU needed if you set
`GENETIC_TRACTABILITY_LLM_BASE_URL` at a local Ollama instance for the
quick test, or just run `--phase all --no-llm --max-papers 25` to validate
discovery+screening without touching an LLM at all).

## Submitting the real pipeline

```bash
mkdir -p logs
sbatch --account=<your-account> cluster/run_v2_discovery.sbatch
sbatch --account=<your-account> --dependency=afterok:<job_id> cluster/run_v2_screen.sbatch
sbatch --account=<your-account> --dependency=afterok:<job_id> cluster/run_v2_extract.sbatch
```

Optional env vars at submit time:

```bash
sbatch --export=ALL,MAX_PAPERS=500,CITATION_DEPTH=2 cluster/run_v2_discovery.sbatch
sbatch --export=ALL,MAX_PAPERS=1000 cluster/run_v2_screen.sbatch
sbatch --export=ALL,MAX_PAPERS=1000,MODEL=Qwen/Qwen3-4B-Instruct-2507 cluster/run_v2_extract.sbatch
```

Every phase is resumable by construction (SQLite `processing_status`
column, not a CSV set-difference) -- resubmitting any of these three jobs
only processes what's not already at the target status for that phase.

## Checking status

```bash
cd scripts
python3 -c "
from attempt_db import get_connection
conn = get_connection()
for row in conn.execute('SELECT processing_status, COUNT(*) c FROM papers GROUP BY processing_status'):
    print(row['processing_status'], row['c'])
print('attempts:', conn.execute('SELECT COUNT(*) c FROM engineering_attempts').fetchone()['c'])
"
```

Or just run the reports phase again (cheap, DB-read-only, regenerates
`reports/*.csv` and prints the full summary from spec section 37/38):

```bash
python3 run_engineering_discovery.py --phase reports
```

## Results

`data/genetic_tractability/reports/*.csv` -- `discovered_papers.csv`,
`high_priority_candidates.csv`, `fulltext_unavailable.csv`,
`engineering_attempts.csv`, `failures.csv`, `successes.csv`,
`partial_successes.csv`, `needs_review.csv`. Judge the pipeline by
`engineering_attempts.csv`'s row count and specifically `failures.csv`'s
row count (spec section 38) -- not by how many papers were discovered.
