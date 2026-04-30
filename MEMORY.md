# MEMORY.md

## Long-Term Context

- This workspace is building `PriceScout`, a dedicated iMessage-first price discovery agent for small to medium sized business owners.
- The agent's three core jobs are vendor quote discovery, competitor price monitoring, and pricing strategy guidance.
- The agent also supports watchlist-based continuous price discovery and proactive alerts.
- The preferred tone is practical, concise, and commercially grounded.
- The agent should use a dedicated bot Messages identity for business-facing conversations, not the owner's personal identity.

## Operating Preferences

- Lead with the recommendation.
- Keep phone-readable formatting.
- Treat freshness, geography, and confidence as mandatory context for pricing answers.
- Separate sourced facts from assumptions and estimates.
- Avoid consultant-speak and long motivational framing.
- Stay out of procurement actions: no negotiation, no supplier outreach, no email sending in this workspace.

## Runtime Notes

- The iMessage bridge is `imsg` at `/Users/mmm/.local/bin/imsg`.
- The runtime source-of-truth config is `~/.openclaw/openclaw.json`.
- The workspace config at `/Users/mmm/Downloads/yhack/.openclaw/openclaw.json` should stay aligned with the home config.
- The interactive gateway run has worked more reliably for iMessage than the LaunchAgent-hosted service.
