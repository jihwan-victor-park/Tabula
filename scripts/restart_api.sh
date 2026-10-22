#!/usr/bin/env bash
# Restart only the API (port 8080) of a running scripts/dev.sh stack, e.g. after a backend change.
set -euo pipefail
cd "$(dirname "$0")/.."
lsof -ti:8080 | xargs kill 2>/dev/null || true
sleep 1
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://localhost/tabula_dev}" TABULA_ENV=development TABULA_AUTH_MODE=dev \
  TABULA_SUPPLIER_SEND_MODE=capture SQUARE_ENVIRONMENT="${SQUARE_ENVIRONMENT:-mock}" TABULA_CORS_ORIGINS=http://127.0.0.1:5173
[[ -z "${TABULA_TOKEN_ENCRYPTION_KEY:-}" && -f var/dev_token_encryption_key ]] && export TABULA_TOKEN_ENCRYPTION_KEY="$(cat var/dev_token_encryption_key)"
nohup .venv/bin/python -m uvicorn clawbot.api.app:app --host 127.0.0.1 --port 8080 > var/log/api.log 2>&1 &
for _ in $(seq 1 30); do curl -sf -o /dev/null http://127.0.0.1:8080/docs && echo "API restarted" && exit 0; sleep 1; done
echo "API did not come up; see var/log/api.log" >&2; exit 1
