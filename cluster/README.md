# Running this pipeline on HPC2 (Orion)

## Why four jobs, not one

Same split fair_ocean_agent's `cluster/README.md` uses, for the same
reason: this cluster's GPU nodes have no internet access, and the
service/CPU partition has no GPU. This pipeline has an extra wrinkle
fair_ocean_agent doesn't: genome-accession resolution (NCBI) only knows
what organism/strain to look up *after* the LLM extraction stage runs, so
it can't be pre-warmed the way abstract/full-text fetches can -- it needs
its own internet-capable pass, after the GPU job, not before it.

1. **`run_discovery.sbatch`** (CPU, `service` partition, internet) --
   review discovery, broad/negative keyword search, review-reference and
   review-table extraction. No LLM. Populates `data/genetic_tractability/candidate_papers.csv`.
2. **`run_prefetch.sbatch`** (CPU, `service` partition, internet) -- fetches
   each candidate's abstract (and full text, if open access) from Europe
   PMC, warming `data/cache/`. No LLM. This is what lets the GPU job run
   with zero internet access.
3. **`run_extraction.sbatch`** (GPU, `gpu-a100` partition, no internet) --
   starts `vllm serve`, runs abstract triage (script 13), keyword-span
   tagging (script 14, no LLM, reads the warm cache), and structured
   extraction (script 15). Produces `manipulation_observations_auto.csv`.
4. **`run_genome_matching.sbatch`** (CPU, `service` partition, internet) --
   resolves each extracted organism/strain against NCBI assembly. Produces
   `genome_matches_auto.csv`.

All four share the same filesystem (`data/cache/`, `data/genetic_tractability/*.csv`)
-- normal on HPC, since these are just files under the repo checkout on
shared home/scratch storage.

**vLLM only, not Ollama.** Ollama on a Mac CPU proved too slow and missed
real signal for this task (confirmed by direct comparison) -- an A100
running vLLM is the actual fix, not a bigger local model. `llm_client.py`
speaks the same OpenAI-compatible wire protocol either way
(`GENETIC_TRACTABILITY_LLM_BASE_URL`/`GENETIC_TRACTABILITY_LLM_MODEL` env
vars switch it), so no pipeline code changes were needed for the swap --
`run_extraction.sbatch` just sets those two env vars after `vllm serve`
comes up.

## One-time setup

```bash
# On a login node (needs internet):
git clone <this-repo-url> genetic_tractability
cd genetic_tractability
CONDA_ENV_PREFIX=/scratch/hmp278/conda_envs/genetic-tractability ./cluster/setup_env.sh
conda activate /scratch/hmp278/conda_envs/genetic-tractability

# GPU/vLLM extras, same env:
pip install vllm
# vllm pulls in flashinfer for CUDA kernel fusion; versions before
# 0.6.16.post4 have a type annotation that only evaluates on Python 3.12+,
# so `vllm serve` crashes at model load on 3.10/3.11 with "TypeError: type
# 'array.array' is not subscriptable" (same issue fair_ocean_agent's
# cluster/README.md documents -- this is the identical cluster/account).
pip install "flashinfer-python>=0.6.16.post4"

# One-time model download (needs internet -- run from a login node):
./cluster/download_vllm_model.sh   # defaults to Qwen/Qwen3-4B-Instruct-2507
```

## Running discovery on your Mac first, then syncing up

Same reasoning as fair_ocean_agent's cluster docs: `ingest`/discovery
scripts here are all accumulate-and-dedupe against whatever's already in
`candidate_papers.csv`/`data/cache/`, so running discovery locally first
and syncing avoids the cluster re-hitting Europe PMC for papers your Mac
already resolved:

```bash
# On your Mac, once your local discovery run has finished:
./cluster/sync_local_data_to_cluster.sh hpc2 /scratch/hmp278/genetic_tractability
```

Then submit `run_discovery.sbatch` as usual -- it only does network work
for what's new.

## Submitting the pipeline

```bash
mkdir -p logs
sbatch --account=<your-account> cluster/run_discovery.sbatch
# wait for it (squeue -u $USER), or chain with --dependency:
sbatch --account=<your-account> --dependency=afterok:<job_id> \
  --export=ALL,BATCH_SIZE=500 cluster/run_prefetch.sbatch
sbatch --account=<your-account> --dependency=afterok:<job_id> \
  --export=ALL,BATCH_SIZE=500,MODEL=Qwen/Qwen3-4B-Instruct-2507 cluster/run_extraction.sbatch
sbatch --account=<your-account> --dependency=afterok:<job_id> cluster/run_genome_matching.sbatch
```

`BATCH_SIZE` must match between `run_prefetch.sbatch` and
`run_extraction.sbatch` -- prefetch warms the cache for exactly that many
untriaged candidates (in the same priority order `batch_selection.py`
uses), and extraction processes that same batch. Re-running with a larger
`BATCH_SIZE` after a first pass only processes the newly-added candidates
(scripts 13/14/15 all skip paper_ids already present in their output
files), so scaling up is additive, not a redo.

Check progress:

```bash
tail -f logs/discovery_<job_id>.out      # or prefetch_/extraction_/genome_matching_<job_id>.out
tail -f logs/vllm_<job_id>.log           # vllm server's own log, inside the extraction job
wc -l data/genetic_tractability/abstract_triage.csv               # triage progress
wc -l data/genetic_tractability/manipulation_observations_auto.csv # extraction progress
```

Results land in `data/genetic_tractability/manipulation_observations_auto.csv`
and `genome_matches_auto.csv`. Pull them back to your Mac:

```bash
scp <cluster>:<path>/genetic_tractability/data/genetic_tractability/*_auto.csv ./data/genetic_tractability/
```

## Scaling up

Same four jobs, larger `BATCH_SIZE` (and re-run `run_discovery.sbatch`
periodically to pull in fresh review papers / table references as the
candidate pool grows). Worth doing in batches of a few hundred rather than
the full candidate pool at once, at least for the first real large-scale
run on this cluster -- easier to notice and retry a stuck batch than debug
a single multi-day job.

## Troubleshooting

- **`sbatch: error: Invalid partition`**: partition names here
  (`service`, `gpu-a100`) are copied from `fair_ocean_agent/cluster/`'s own
  jobs on this same account -- confirm with `sinfo` and edit the
  `#SBATCH --partition=` lines if this is a different account/allocation.
- **`run_extraction.sbatch` hangs or times out waiting for vllm**: check
  `logs/vllm_<job_id>.log` directly -- a model that wasn't downloaded
  first (see `download_vllm_model.sh`) fails there with a clear
  `HF_HUB_OFFLINE` error rather than in the main log.
- **`logs/vllm_<job_id>.log` shows `TypeError: type 'array.array' is not
  subscriptable` in `flashinfer/comm/fd_exchange.py`**: old
  `flashinfer-python` -- `pip install "flashinfer-python>=0.6.16.post4"`
  in the same env, resubmit.
- **`run_discovery.sbatch`/`run_prefetch.sbatch` fail with connection
  errors**: that partition doesn't actually have outbound internet --
  test with `curl https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=test&pageSize=1`
  from an interactive session on that partition before submitting a real job.
- **Re-running is safe**: every stage here only processes what's actually
  new (candidate dedup in `candidate_store.py`, paper_id skip-lists in
  scripts 13/14/15), so a failed or interrupted job can just be
  resubmitted.
