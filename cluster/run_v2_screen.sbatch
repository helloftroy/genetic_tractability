#!/bin/bash
# v2 pipeline stage 2: deterministic screening + PMC BioC full-text fetch
# (spec sections 14-15). CPU, needs internet (fetches BioC full text per
# candidate paper). Writes chunks_v2/<paper_id>.json for anything that
# scores relevant -- this is the ONLY stage that touches the network for
# full text, so run_v2_extract.sbatch's GPU node needs none at all.
#SBATCH --job-name=genetic_tractability_v2_screen
#SBATCH --partition=service
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=48:00:00
#SBATCH --output=logs/v2_screen_%j.out
#SBATCH --error=logs/v2_screen_%j.err

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

cd scripts
python3 run_engineering_discovery.py --phase screen ${MAX_PAPERS_ARG}

echo "=== v2 screening stage complete ==="
python3 -c "
from attempt_db import get_connection
conn = get_connection()
for row in conn.execute('SELECT processing_status, COUNT(*) c FROM papers GROUP BY processing_status'):
    print(f\"  {row['processing_status']}: {row['c']}\")
"

echo "Job finished: $(date)"
echo "Next: submit cluster/run_v2_extract.sbatch (GPU, LLM_BACKEND=vllm)"
