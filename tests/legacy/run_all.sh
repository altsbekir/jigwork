#!/usr/bin/env bash
# Runs every legacy test. Exit code 0 only if all pass.
cd "$(dirname "$0")"
rc=0
echo "=== security probes";      bash security_probes.sh  || rc=1
echo; echo "=== orchestrator e2e"; bash orchestrator_e2e.sh || rc=1
exit $rc
