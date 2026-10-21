#!/bin/bash
set -e

cd "$(dirname "$0")"

# Kill any existing server on port 8000
lsof -ti:8000 | xargs kill -9 2>/dev/null || true

# Start API in background
uvicorn clawbot.api.price_routes:app --port 8000 &
sleep 2

# Add pebble toys watch item (upsert — safe to run multiple times)
curl -s -X POST http://127.0.0.1:8000/watchlist \
  -H "Content-Type: application/json" \
  -d '{
    "id": "pebble-toys",
    "label": "Pebble Toys",
    "mode": "competitor",
    "active": true,
    "region": "US",
    "query": "https://pebblestoys.com/?srsltid=AfmBOooLKDqDjuAsc2Ajx8D03YqwJaa1i6oBRh0sP_xGQi2G53VNvW2D",
    "baseline": {"supplier": "Current Supplier", "price": 25.00, "currency": "USD"},
    "threshold_pct": 5.0
  }' > /dev/null

# Run the scan and display report
python3 price_cli.py scan --business "Your Store" --location "US"

# Send digest via iMessage (scan already ran, just fetch alerts and send)
python3 imsg_cli.py send \
  --business "Your Store" \
  --location "US" \
  --recipient "${TABULA_DEMO_RECIPIENT:?Set TABULA_DEMO_RECIPIENT to the phone number that should receive the demo}" \
  --no-trends

# Stop the background server
kill %1 2>/dev/null || true
