#!/bin/bash
# Run onboarding via iMessage, then start the full PriceScout stack.
# Usage: ./onboarding.sh --to +15551234567
#        ./onboarding.sh --to +15551234567 --force

set -e
cd "$(dirname "$0")"

if [ "$#" -eq 0 ]; then
  echo "Usage: ./onboarding.sh --to <phone_or_email> [--force]"
  exit 1
fi

echo "Starting onboarding..."
python3 onboarding_cli.py "$@"

echo ""
echo "Onboarding complete. Starting stack..."
bash start.sh
