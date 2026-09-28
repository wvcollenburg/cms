#!/usr/bin/env bash
# Calls the daily task API (D21, PLAN §10a) with an HMAC signature. Run it once a day from cron
# on a server other than the website, e.g. /etc/cron.d/createur-tasks:
#   15 3 * * * createur CREATEUR_TASK_SECRET=... /opt/createur/call-tasks.sh https://<domain>
# Needs: bash, curl, openssl. Exits non-zero when a task failed or the site didn't answer,
# so cron mails the output (or your own monitoring notices).
#   call-tasks.sh BASE_URL [TASK...]     e.g. call-tasks.sh https://example.nl cache_rebuild
set -euo pipefail
BASE_URL=${1:?usage: call-tasks.sh BASE_URL [TASK...]}
shift
: "${CREATEUR_TASK_SECRET:?set CREATEUR_TASK_SECRET to the TASK_SECRET of the website}"

if [ $# -gt 0 ]; then
  BODY=$(printf '"%s",' "$@")
  BODY="{\"tasks\": [${BODY%,}]}"
else
  BODY='{}'
fi
TS=$(date +%s)
SIG=$(printf '%s%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$CREATEUR_TASK_SECRET" -hex | awk '{print $NF}')

curl -fsS --max-time 120 -X POST "${BASE_URL%/}/api/tasks/run" \
  -H "Content-Type: application/json" -H "X-Task-Timestamp: $TS" -H "X-Task-Signature: $SIG" \
  --data "$BODY"
echo
