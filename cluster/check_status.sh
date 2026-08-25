#!/usr/bin/env bash
# One-command status check: is anything running/queued right now, how did
# the most recent jobs of each type actually end (completed/failed/timed
# out/OOM-killed -- not just "did it print something recently"), what do
# their logs' tails say, and what's the current pipeline data/backlog state.
#
# Usage: ./cluster/check_status.sh
set -uo pipefail   # deliberately not -e: a missing log file or empty sacct
                    # result should not abort the whole status check
cd "$(dirname "$0")/.."   # repo root (genetic_tractability/)

echo "================================================================"
echo "QUEUE/RUNNING JOBS"
echo "================================================================"
squeue -u "$USER" 2>&1 || echo "(squeue failed -- are you on a node with SLURM commands available?)"

echo
echo "================================================================"
echo "RECENT JOB HISTORY (last 3 days) -- State/ExitCode is the real"
echo "answer to \"did it finish\": COMPLETED+0:0 = finished cleanly,"
echo "TIMEOUT = hit --time, OUT_OF_MEMORY = OOM-killed, FAILED = a real"
echo "error (check its log below)."
echo "================================================================"
sacct -u "$USER" --starttime=now-3days \
  --format=JobID%14,JobName%28,State%12,ExitCode%8,Elapsed%10,Start%19 \
  2>&1 || echo "(sacct failed -- try 'sacct -u \$USER' manually to see the real error)"

echo
echo "================================================================"
echo "LATEST LOG PER STAGE (last 15 lines of the most recently modified"
echo "logs/*.out for each job type)"
echo "================================================================"
for prefix in discovery prefetch extraction genome_matching; do
  latest=$(ls -t logs/${prefix}_*.out 2>/dev/null | head -1)
  if [ -n "${latest:-}" ]; then
    echo "--- ${latest} ---"
    tail -15 "${latest}"
    echo
  else
    echo "--- no logs/${prefix}_*.out found yet ---"
    echo
  fi
done

latest_vllm=$(ls -t logs/vllm_*.log 2>/dev/null | head -1)
if [ -n "${latest_vllm:-}" ]; then
  echo "--- ${latest_vllm} (vLLM server's own log -- check this if extraction"
  echo "    looks stalled with no errors in the main log; a wedged/crashed"
  echo "    vLLM server won't necessarily say so anywhere else) ---"
  tail -15 "${latest_vllm}"
  echo
fi

echo "================================================================"
echo "CURRENT DATA STATE + BACKLOG"
echo "================================================================"
if [ -f cluster/env_activate.sh ]; then
  # shellcheck source=/dev/null
  source cluster/env_activate.sh
fi
(cd scripts && python3 17_data_state_report.py) 2>&1 || echo "(state report failed -- check the python environment is activated)"
