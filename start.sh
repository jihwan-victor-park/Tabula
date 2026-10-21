#!/bin/bash
# Start the full PriceScout stack.
# Reads recipient and forward-url from .openclaw/onboarding.json if present.

set -e
cd "$(dirname "$0")"

# Load .env into the environment so all child processes inherit the keys
if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PORTS=(8000 8003 8004 8006 8007)

# Kill anything on our ports
for port in "${PORTS[@]}"; do
  lsof -ti:$port | xargs kill -9 2>/dev/null || true
done

# Load onboarding config for recipient if available
RECIPIENT=""
if [ -f ".openclaw/onboarding.json" ]; then
  RECIPIENT=$(python3 -c "import json; d=json.load(open('.openclaw/onboarding.json')); print(d.get('recipient',''))" 2>/dev/null || true)
fi
RECIPIENT="${RECIPIENT:-${TABULA_DEFAULT_RECIPIENT:-}}"
if [ -z "$RECIPIENT" ]; then
  echo "No iMessage recipient. Run onboarding.sh or set TABULA_DEFAULT_RECIPIENT in .env" >&2
  exit 1
fi

echo "Starting PriceScout stack..."
echo "  iMessage recipient: $RECIPIENT"
echo ""

# Start all FastAPI servers in the background
uvicorn clawbot.api.price_routes:app --port 8000 --log-level warning &
echo "  [8000] price scout"

uvicorn clawbot.api.procurement_routes:app --port 8003 --log-level warning &
echo "  [8003] procurement"

uvicorn clawbot.api.inventory_routes:app --port 8004 --log-level warning &
echo "  [8004] inventory"

uvicorn clawbot.api.universal_routes:app --port 8006 --log-level warning &
echo "  [8006] universal agent"

sleep 2

# Start clawbot last — it listens for iMessages and forwards to universal agent
python -m clawbot.main serve-api \
  --port 8007 \
  --watch-recipient "$RECIPIENT" \
  --forward-url http://localhost:8006/ask/internal &
echo "  [8007] clawbot gateway → universal agent"

echo ""
echo "Stack is up. Send an iMessage to $RECIPIENT to talk to your agent."
echo "Press Ctrl+C to stop everything."

# Wait and clean up on exit
trap 'echo ""; echo "Shutting down..."; kill $(jobs -p) 2>/dev/null; exit' INT TERM
wait
