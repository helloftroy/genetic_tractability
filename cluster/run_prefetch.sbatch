#!/bin/bash
# Stage 2: warm the response cache for the batch scripts 13/14 will process,
# BEFORE the GPU job runs (GPU nodes on this cluster have no internet --
# same reasoning as fair_ocean_agent/cluster/README.md's "why two jobs, not
# one"). Fetches each candidate paper's abstract and (if open access) full
# text via Europe PMC; makes no LLM calls at all. Must run against the same
# data/cache/ directory run_extraction.sbatch will read (normal on HPC,
# same shared home/scratch filesystem).
#
# BATCH_SIZE controls how many untriaged candidates to prefetch for --
# script 13/14 process exactly this same batch (batch_selection.py), so
# raise this to prefetch a bigger batch in one shot; default matches the
# batch size validated on a Mac before this cluster split was built.
#SBATCH --job-name=genetic_tractability_prefetch
#SBATCH --partition=service
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=06:00:00
#SBATCH --output=logs/prefetch_%j.out
#SBATCH --error=logs/prefetch_%j.err

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

BATCH_SIZE="${BATCH_SIZE:-350}"
echo "Batch size: ${BATCH_SIZE}"

cd scripts
python3 12b_prefetch_llm_batch.py "${BATCH_SIZE}"

echo "Job finished: $(date)"
echo "Next: submit cluster/run_extraction.sbatch (GPU, LLM_BACKEND=vllm) with the same BATCH_SIZE."
