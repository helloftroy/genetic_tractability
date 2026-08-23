#!/usr/bin/env bash
# Pushes this Mac's discovery run (candidate_papers.csv, review_seeds.csv,
# etc. + the warm data/cache/) up to the cluster, so run_discovery.sbatch
# tops up what's missing instead of re-discovering everything from scratch
# and re-hitting Europe PMC/NCBI for papers already resolved here.
#
# Run this FROM YOUR MAC, after a local discovery run has finished.
#
# Usage: ./cluster/sync_local_data_to_cluster.sh <ssh-alias> <remote-repo-path>
# Example: ./cluster/sync_local_data_to_cluster.sh hpc2 /scratch/hmp278/genetic_tractability
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root (genetic_tractability/)

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 <ssh-alias> <remote-repo-path>" >&2
  echo "Example: $0 hpc2 /scratch/hmp278/genetic_tractability" >&2
  exit 2
fi
CLUSTER="$1"
REMOTE_PATH="$2"

echo "Syncing data/genetic_tractability/ (CSV outputs) -> ${CLUSTER}:${REMOTE_PATH}/data/genetic_tractability/"
rsync -avz --exclude 'keyword_spans/' data/genetic_tractability/ "${CLUSTER}:${REMOTE_PATH}/data/genetic_tractability/"

echo "Syncing data/cache/ (warm HTTP response cache -- avoids re-fetching anything already cached)"
rsync -avz data/cache/ "${CLUSTER}:${REMOTE_PATH}/data/cache/"

echo
echo "Done. On the cluster, run_discovery.sbatch (and run_prefetch.sbatch) against this"
echo "same repo checkout will now skip anything already discovered/cached locally."
