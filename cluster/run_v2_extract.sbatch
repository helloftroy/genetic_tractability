#!/bin/bash
# v2 pipeline stage 3: LLM extraction into engineering_attempts (spec
# sections 16-30). GPU, needs NO internet at all -- extract_v2.py only
# ever reads local chunks_v2/*.json (written by run_v2_screen.sbatch) and
# writes to the local SQLite DB, no network calls anywhere in that code
# path. Simpler than the v1 pipeline's GPU stage (run_extraction.sbatch),
# which needed a CACHE_ONLY/prefetch-matching dance because its scripts
# 13/14 DO make network calls that might not be cached -- extract_v2.py
# was designed from the start to never need that.
#SBATCH --job-name=genetic_tractability_v2_extract
#SBATCH --partition=gpu-a100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=48:00:00
#SBATCH --output=logs/v2_extract_%j.out
#SBATCH --error=logs/v2_extract_%j.err

set -euo pipefail
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
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-unset}"

if ! command -v vllm >/dev/null 2>&1; then
  echo "vllm not found on PATH. Install it in this env first (see cluster/README.md):" >&2
  echo "  pip install vllm 'flashinfer-python>=0.6.16.post4'" >&2
  exit 2
fi

MODEL="${MODEL:-Qwen/Qwen3-4B-Instruct-2507}"
export HF_HOME="${HF_HOME:-$(pwd)/cluster/hf_cache}"
export HF_HUB_OFFLINE=1
export VLLM_USE_FLASHINFER_SAMPLER=0
export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

echo "Starting vllm serve (model=${MODEL}, HF_HOME=${HF_HOME})..."
vllm serve "${MODEL}" --host 0.0.0.0 --port 8000 > "logs/v2_vllm_${SLURM_JOB_ID:-local}.log" 2>&1 &
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
  echo "vllm did not become responsive in time -- check logs/v2_vllm_${SLURM_JOB_ID:-local}.log" >&2
  exit 1
fi

export GENETIC_TRACTABILITY_LLM_BASE_URL="http://localhost:8000/v1"
export GENETIC_TRACTABILITY_LLM_MODEL="${MODEL}"

MAX_PAPERS_ARG=""
if [ -n "${MAX_PAPERS:-}" ]; then MAX_PAPERS_ARG="--max-papers ${MAX_PAPERS}"; fi

cd scripts
python3 run_engineering_discovery.py --phase extract ${MAX_PAPERS_ARG}
python3 run_engineering_discovery.py --phase reports

echo "Job finished: $(date)"
echo "Results: data/genetic_tractability/reports/*.csv"
