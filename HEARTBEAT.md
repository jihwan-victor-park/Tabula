# HEARTBEAT.md

Run PriceScout as a quiet background price monitor.

On each heartbeat:

1. Read `.openclaw/price-scout/settings.json`, `.openclaw/price-scout/watchlist.json`, `.openclaw/price-scout/findings.json`, and `.openclaw/price-scout/alerts.json`.
2. If there are no active watchlist items, reply `HEARTBEAT_OK`.
3. Scan only up to the configured per-run limit.
4. Use the live `web_search` tool for current public price signals before saying live data is unavailable.
5. Update the findings file and alert history if a watched item beats its baseline threshold.
6. If there is no new alert-worthy change, reply `HEARTBEAT_OK`.
7. If there is a new alert-worthy change, send one concise owner-facing message with:
   - watched item
   - current baseline
   - better market option found
   - estimated savings or delta
   - one suggested next step

Never send outreach, negotiation, or procurement actions during heartbeat runs.
If `web_search` actually fails, say that it failed and why. Do not guess that the Gemini key is missing unless the tool call itself proves that.
