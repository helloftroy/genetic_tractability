#!/bin/bash
# Stage 1: paper discovery. No LLM calls at all -- this is the HTTPS-capable,
# CPU-only half of the pipeline (Europe PMC E-utilities). Runs scripts
# 01-04, 12, 11 (review discovery, broad/negative keyword search,
# review-reference extraction, review-table extraction, title cleanup).
# Warms data/cache/ for everything it touches -- run_prefetch.sbatch and
# run_extraction.sbatch later read that same cache.
#
# Partition name is copied from fair_ocean_agent/cluster/run_discovery.sbatch
# (same cluster, same account) as a starting point -- confirm with `sinfo`
# before submitting if this is a fresh account/allocation.
#
# Discovery-depth knobs (all optional, default to a moderate-but-real
# scope -- raise them to search deeper into the same Europe PMC queries'
# hit lists via cursorMark pagination, which fetches genuinely new pages,
# not cache replays, as long as that depth was not already fetched by a
# prior run):
#   sbatch --export=ALL,GT_REVIEW_PER_TOPIC=25,GT_REVIEW_FETCH_PER_TOPIC=150,\
#     GT_REVIEW_OLD_YEAR_PER_TOPIC=15,GT_BROAD_PER_QUERY=500,GT_NEGATIVE_PER_QUERY=400 \
#     cluster/run_discovery.sbatch
# This does NOT pick up newly-published papers matching queries you've
# already exhausted -- that needs clearing data/cache/ (not done here on
# purpose, since a full clear re-fetches everything from scratch and this
# job is meant to stay fast/incremental). It only reaches further into the
# existing relevance/citation-ranked result lists.
#SBATCH --job-name=genetic_tractability_discovery
#SBATCH --partition=service
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=48:00:00
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
python3 17_data_state_report.py

echo "Job finished: $(date)"
echo "Next: submit cluster/run_prefetch.sbatch (same repo checkout, same filesystem)."
