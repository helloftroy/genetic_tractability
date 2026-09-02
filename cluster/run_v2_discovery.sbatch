#!/bin/bash
# v2 pipeline stage 1: NCBI/PubMed discovery + citation expansion (spec
# sections 6-13). CPU, needs internet. NOT the same pipeline as
# run_discovery.sbatch (v1, Europe PMC-based) -- this is the separate
# NCBI/PubMed/PMC-based system in scripts/run_engineering_discovery.py.
# OpenAlex is never used here (see that script's module docstring).
#SBATCH --job-name=genetic_tractability_v2_discovery
#SBATCH --partition=service
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=48:00:00
#SBATCH --output=logs/v2_discovery_%j.out
#SBATCH --error=logs/v2_discovery_%j.err

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

MAX_PAPERS_ARG=""
if [ -n "${MAX_PAPERS:-}" ]; then MAX_PAPERS_ARG="--max-papers ${MAX_PAPERS}"; fi
ORGANISM_FILE_ARG=""
if [ -n "${ORGANISM_FILE:-}" ]; then ORGANISM_FILE_ARG="--organism-file ${ORGANISM_FILE}"; fi
CITATION_DEPTH="${CITATION_DEPTH:-1}"

cd scripts
python3 run_engineering_discovery.py --phase pubmed-search ${MAX_PAPERS_ARG} ${ORGANISM_FILE_ARG}
python3 run_engineering_discovery.py --phase citations --citation-depth "${CITATION_DEPTH}" ${MAX_PAPERS_ARG}

echo "=== v2 discovery stage complete ==="
python3 -c "
from attempt_db import get_connection
conn = get_connection()
print('Total papers in DB:', conn.execute('SELECT COUNT(*) c FROM papers').fetchone()['c'])
for row in conn.execute('SELECT processing_status, COUNT(*) c FROM papers GROUP BY processing_status'):
    print(f\"  {row['processing_status']}: {row['c']}\")
"

echo "Job finished: $(date)"
echo "Next: submit cluster/run_v2_screen.sbatch"
