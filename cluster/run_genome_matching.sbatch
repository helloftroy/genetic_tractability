#!/bin/bash
# Stage 4: genome accession resolution against NCBI assembly. Needs
# internet again (NCBI E-utilities weren't warmed by run_prefetch.sbatch --
# the exact organism/strain names to look up aren't known until AFTER
# run_extraction.sbatch's LLM stage produces them), so this runs back on
# the CPU/service partition, after run_extraction.sbatch completes.
#SBATCH --job-name=genetic_tractability_genome_matching
#SBATCH --partition=service
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=04:00:00
#SBATCH --output=logs/genome_matching_%j.out
#SBATCH --error=logs/genome_matching_%j.err

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
cd scripts
python3 09_genome_matching.py manipulation_observations_auto.csv genome_matches_auto.csv

echo "Job finished: $(date)"
echo "Results: data/genetic_tractability/genome_matches_auto.csv"
