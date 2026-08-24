#!/bin/bash
# Stage 1: paper discovery. No LLM calls at all -- this is the HTTPS-capable,
# CPU-only half of the pipeline (Europe PMC + NCBI E-utilities). Runs
# scripts 01-04, 06, 09, 11, 12 (review discovery, broad/negative keyword
# search, review-reference extraction, review-table extraction, genome
# accession matching). Warms data/cache/ for everything it touches --
# run_extraction.sbatch (GPU, no internet) later reads that same cache.
#
# Partition name is copied from fair_ocean_agent/cluster/run_discovery.sbatch
# (same cluster, same account) as a starting point -- confirm with `sinfo`
# before submitting if this is a fresh account/allocation.
#SBATCH --job-name=genetic_tractability_discovery
#SBATCH --partition=service
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=12:00:00
#SBATCH --output=logs/discovery_%j.out
#SBATCH --error=logs/discovery_%j.err

set -euo pipefail

# Real-time log visibility: SLURM redirects stdout to a file (not a TTY),
# which switches Python's print() from line-buffered to block-buffered --
# without this, logs/*.out can appear frozen for a long time even while
# the job is actively working, since nothing gets flushed until a script
# exits or its buffer fills. Confirmed as the actual explanation for a
# real "is this stuck?" report during development.
export PYTHONUNBUFFERED=1
# $(dirname "$0") is not reliable under sbatch (it commonly stages/copies the
# submitted script first) -- SLURM_SUBMIT_DIR reliably points back at
# wherever `sbatch` was actually invoked from instead.
: "${SLURM_SUBMIT_DIR:?SLURM_SUBMIT_DIR is unset -- this script must be run via sbatch, not directly.}"
cd "${SLURM_SUBMIT_DIR}"   # repo root (genetic_tractability/)
mkdir -p logs

if [ ! -f cluster/env_activate.sh ]; then
  echo "cluster/env_activate.sh is missing -- run ./cluster/setup_env.sh first." >&2
  exit 2
fi
# shellcheck source=/dev/null
source cluster/env_activate.sh

echo "Job started: $(date)"
echo "Host: $(hostname)"
echo "Working directory: $(pwd)"
python --version

cd scripts

echo "=== 01: review discovery ==="
python3 01_discover_reviews.py

echo "=== 02: broad keyword discovery ==="
python3 02_broad_keyword_discovery.py

echo "=== 03: negative-enriched (failure) discovery ==="
python3 03_negative_keyword_discovery.py

echo "=== 04: review reference extraction ==="
python3 04_review_reference_extraction.py

echo "=== 12: review table extraction ==="
python3 12_extract_review_tables.py

echo "=== 11: clean HTML from title fields ==="
python3 11_clean_titles.py

echo "=== discovery stage complete ==="
python3 - <<'PYEOF'
import csv
with open("../data/genetic_tractability/candidate_papers.csv") as f:
    rows = list(csv.DictReader(f))
print(f"candidate_papers.csv: {len(rows)} rows "
      f"({sum(1 for r in rows if r['is_review']=='True')} reviews)")
PYEOF

echo "Job finished: $(date)"
echo "Next: submit cluster/run_prefetch.sbatch (same repo checkout, same filesystem)."
