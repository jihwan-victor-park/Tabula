# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for the local details that matter to this specific agent deployment.

## OpenClaw Runtime

- Runtime source of truth: `~/.openclaw/openclaw.json`
- Workspace mirror config: `/Users/mmm/Downloads/yhack/.openclaw/openclaw.json`
- iMessage bridge binary: `/Users/mmm/.local/bin/imsg`
- `imsg` resource bundles live next to the binary in `/Users/mmm/.local/bin/`
- iMessage gateway currently works reliably when run interactively with `openclaw gateway run --verbose`

## iMessage Deployment Notes

- Production intent is a dedicated bot Messages identity, not the owner's personal identity.
- Keep `dmPolicy` on pairing and keep groups allowlisted unless explicitly opened for a business use case.
- If iMessage stops reading `chat.db`, re-check Full Disk Access and whether the gateway was launched interactively or as a background service.

## Business Defaults

- Primary interface: iMessage DMs
- Primary job: SMB price discovery
- Core workflows: vendor quotes, competitor monitoring, pricing strategy, and watchlist-based monitoring
- Preferred answer style: concise, actionable, source-aware

## Reliability Notes

- The LaunchAgent-hosted gateway may not inherit the same macOS privacy access as the interactive run.
- If channel health regresses after a restart, confirm which config the running gateway loaded and re-test `openclaw channels status --probe`.
- Gemini-backed live web search is enabled via `GEMINI_API_KEY` in `~/.openclaw/.env`.
- After changing `~/.openclaw/.env`, restart the interactive gateway so the provider environment is reloaded.

## PriceScout State

- Structured state lives in `/Users/mmm/Downloads/yhack/.openclaw/price-scout/`
- Owner-facing watchlist management CLI: `python3 scripts/price_scout.py`
- Heartbeat is configured in `~/.openclaw/openclaw.json` to scan active watch items and only alert when a meaningful change is found

---

Add more environment-specific details here as the deployment matures.
