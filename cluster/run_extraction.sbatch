#!/bin/bash
# Stage 3: LLM extraction (triage + structured extraction). GPU, NO internet
# needed -- every abstract/full-text fetch scripts 13/14 might otherwise
# make was already warmed into data/cache/ by run_prefetch.sbatch. vLLM
# only (not Ollama): Ollama proved too slow/missed real signal on a Mac CPU
# for this task, per direct comparison -- an A100 running vLLM is the real
# fix, not a bigger local model.
#
# Partition/gres copied from fair_ocean_agent/cluster/run_extraction.sbatch
# (same cluster, same account) as a starting point -- confirm with `sinfo`
# before submitting if this is a fresh account/allocation.
#SBATCH --job-name=genetic_tractability_extraction
#SBATCH --partition=gpu-a100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --output=logs/extraction_%j.out
#SBATCH --error=logs/extraction_%j.err

set -euo pipefail

# Real-time log visibility: SLURM redirects stdout to a file (not a TTY),
# which switches Python's print() from line-buffered to block-buffered --
# without this, logs/*.out can appear frozen for a long time even while
# the job is actively working, since nothing gets flushed until a script
# exits or its buffer fills. Confirmed as the actual explanation for a
# real "is this stuck?" report during development.
export PYTHONUNBUFFERED=1
: "${SLURM_SUBMIT_DIR:?SLURM_SUBMIT_DIR is unset -- this script must be run via sbatch, not directly.}"
cd "${SLURM_SUBMIT_DIR}"
mkdir -p logs

if [ ! -f cluster/env_activate.sh ]; then
  echo "cluster/env_activate.sh is missing -- run ./cluster/setup_env.sh first." >&2
  exit 2
fi
# shellcheck source=/dev/null
source cluster/env_activate.sh

echo "Job started: $(date)"
echo "Host: $(hostname)"
python --version
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-unset}"

if ! command -v vllm >/dev/null 2>&1; then
  echo "vllm not found on PATH. Install it in this env first (see cluster/README.md):" >&2
  echo "  pip install vllm 'flashinfer-python>=0.6.16.post4'" >&2
  exit 2
fi

MODEL="${MODEL:-Qwen/Qwen3-4B-Instruct-2507}"
export HF_HOME="${HF_HOME:-$(pwd)/cluster/hf_cache}"
export HF_HUB_OFFLINE=1   # fail fast/clearly if the model wasn't pre-downloaded, rather than hang reaching huggingface.co
# See fair_ocean_agent/cluster/run_extraction.sbatch for why both of these
# are needed on this cluster specifically (confirmed live there): flashinfer
# JIT-compiles a CUDA kernel via nvcc, which GPU compute nodes here don't
# have even though the driver/runtime is present; and a module-injected
# LD_LIBRARY_PATH can shadow this conda env's own libstdc++ with an older
# system one the moment anything pulls in a C++ library.
export VLLM_USE_FLASHINFER_SAMPLER=0
export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

echo "Starting vllm serve (model=${MODEL}, HF_HOME=${HF_HOME})..."
vllm serve "${MODEL}" --host 0.0.0.0 --port 8000 > "logs/vllm_${SLURM_JOB_ID:-local}.log" 2>&1 &
SERVER_PID=$!
trap '[ -n "${SERVER_PID}" ] && kill "${SERVER_PID}" 2>/dev/null || true' EXIT

echo "Waiting for vllm to respond (model loading can take a few minutes)..."
for _ in $(seq 1 60); do
  if curl -s -m 5 http://localhost:8000/v1/models >/dev/null 2>&1; then
    echo "vllm is up."
    break
  fi
  sleep 5
done
if ! curl -s -m 5 http://localhost:8000/v1/models >/dev/null 2>&1; then
  echo "vllm did not become responsive in time -- check logs/vllm_${SLURM_JOB_ID:-local}.log" >&2
  echo "(a missing/uncached model under HF_HUB_OFFLINE=1 will show up there as a clear error --" >&2
  echo "run ./cluster/download_vllm_model.sh from a login node first)" >&2
  exit 1
fi

export GENETIC_TRACTABILITY_LLM_BASE_URL="http://localhost:8000/v1"
export GENETIC_TRACTABILITY_LLM_MODEL="${MODEL}"

BATCH_SIZE="${BATCH_SIZE:-350}"
echo "Batch size: ${BATCH_SIZE} (must match what run_prefetch.sbatch was given)"

cd scripts

echo "=== 13: abstract triage (LLM, reads warm cache) ==="
python3 13_triage_abstracts.py "${BATCH_SIZE}"

echo "=== 14: keyword-span extraction (no LLM, reads warm cache) ==="
python3 14_extract_keyword_spans.py "${BATCH_SIZE}"

echo "=== 15: structured extraction (LLM, reads local keyword-span packets, no network) ==="
python3 15_llm_structured_extraction.py "${BATCH_SIZE}"

echo "=== summary ==="
python3 16_auto_summary_report.py

echo "=== extraction stage complete ==="
python3 17_data_state_report.py

echo "Job finished: $(date)"
echo "Next: submit cluster/run_genome_matching.sbatch to resolve genome accessions"
echo "(needs internet again -- NCBI E-utilities -- so it's a separate CPU-side job)."
