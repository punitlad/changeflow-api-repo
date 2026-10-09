#!/usr/bin/env bash
# Usage: ./run.sh <native-auto-merge|ruleset-bypass|workflow-gated>
# Loads .env.shared + .env.<mode>, injects the App private key from secrets/, and
# starts the API on :8000.
set -euo pipefail

MODE="${1:?usage: ./run.sh <native-auto-merge|ruleset-bypass|workflow-gated>}"
ENV_FILE=".env.$MODE"
KEY_FILE="${CHANGEFLOW_KEY_FILE:-secrets/my-changeflow-app.pem}"

[ -f "$ENV_FILE" ] || { echo "no such mode: $ENV_FILE not found" >&2; exit 1; }
[ -f "$KEY_FILE" ] || { echo "missing $KEY_FILE -- download it from App settings -> Credentials -> Generate a private key" >&2; exit 1; }

set -a
# shellcheck disable=SC1090,SC1091
source .env.shared
source "$ENV_FILE"
set +a
export CHANGEFLOW_APP_PRIVATE_KEY="$(cat "$KEY_FILE")"

: "${CHANGEFLOW_INSTALLATION_ID:?set CHANGEFLOW_INSTALLATION_ID in .env.shared}"
: "${CHANGEFLOW_APPROVER_TOKEN:?set CHANGEFLOW_APPROVER_TOKEN in .env.shared}"

echo "==> $MODE: targeting $CHANGEFLOW_TARGET_OWNER/$CHANGEFLOW_TARGET_REPO (merge_mode=$CHANGEFLOW_MERGE_MODE)"
uvicorn changeflow.api:app --port 8000
