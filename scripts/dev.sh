#!/usr/bin/env bash
# Local Tabula stack: API on 127.0.0.1:8080, import / connector / PO workers, and the UI on :5173.
#   scripts/dev.sh            start everything (Ctrl-C stops all)
#   scripts/dev.sh --seed     also create the demo workspace first (python -m clawbot.devtools.seed_demo)
# Dev sign-in (X-Dev-User) is accepted only from loopback with TABULA_ENV=development; sends are capture-only.
set -euo pipefail
cd "$(dirname "$0")/.."

export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://localhost/tabula_dev}"
export TABULA_ENV=development
export TABULA_AUTH_MODE=dev
export TABULA_SUPPLIER_SEND_MODE=capture
export SQUARE_ENVIRONMENT="${SQUARE_ENVIRONMENT:-mock}"
export TABULA_CORS_ORIGINS=http://127.0.0.1:5173
PY=.venv/bin/python
mkdir -p var/log
# Development-only key for stored connector tokens: created once under var/ (git-ignored, owner-readable only).
# Production uses a key from the secret store (docs/SQUARE_SETUP.md).
if [[ -z "${TABULA_TOKEN_ENCRYPTION_KEY:-}" ]]; then
  if [[ ! -f var/dev_token_encryption_key ]]; then
    (umask 077; "$PY" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" > var/dev_token_encryption_key)
  fi
  export TABULA_TOKEN_ENCRYPTION_KEY="$(cat var/dev_token_encryption_key)"
fi

"$PY" -m alembic upgrade head
if [[ "${1:-}" == "--seed" ]]; then
  "$PY" -m clawbot.devtools.seed_demo
fi

pids=()
trap 'kill "${pids[@]}" 2>/dev/null; wait' EXIT INT TERM
"$PY" -m uvicorn clawbot.api.app:app --host 127.0.0.1 --port 8080 >var/log/api.log 2>&1 & pids+=($!)
for w in import_worker connector_worker po_worker; do
  "$PY" -m "clawbot.workflows.$w" >"var/log/$w.log" 2>&1 & pids+=($!)
done
(cd demo-ui && npx vite --host 127.0.0.1 --port 5173 --strictPort) & pids+=($!)

echo "API  http://127.0.0.1:8080/docs   logs in var/log/"
echo "UI   http://127.0.0.1:5173/ops/setup  (sign in as owner@pawsandco.example after --seed)"
wait
