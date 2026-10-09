#!/usr/bin/env bash
# Usage: ./test-onboard.sh <team-name>
# Fires a POST against a running `./run.sh <mode>` instance and polls until it settles.
set -euo pipefail

TEAM="${1:?usage: ./test-onboard.sh <team-name>}"
BASE="${CHANGEFLOW_API_BASE:-http://localhost:8000}"
REQUESTED_BY="${REQUESTED_BY:-$USER}"

resp=$(curl -sf -X POST "$BASE/team-onboardings" \
  -H 'content-type: application/json' \
  -d "{\"team\":\"$TEAM\",\"requested_by\":\"$REQUESTED_BY\"}")
echo "submitted: $resp"
id=$(echo "$resp" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

while true; do
  job=$(curl -sf "$BASE/team-onboardings/$id")
  phase=$(echo "$job" | python3 -c 'import json,sys; print(json.load(sys.stdin)["phase"])')
  echo "[$(date +%H:%M:%S)] phase=$phase"
  case "$phase" in
    succeeded|failed|already_onboarded) echo "$job" | python3 -m json.tool; break ;;
  esac
  sleep 5
done
