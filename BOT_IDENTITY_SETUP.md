# BOT_IDENTITY_SETUP.md

## Goal

Run PriceScout as a dedicated business-facing iMessage identity instead of the owner's personal Messages account.

## Recommended Setup

1. Create a dedicated Apple ID for the bot.
2. Sign into that Apple ID in `Messages` on the Mac that runs OpenClaw.
3. Prefer a separate macOS user account for the bot if you want stricter isolation.
4. Reconfirm `Messages -> Settings -> iMessage -> Send & Receive` so only the bot identity is exposed for business chats.
5. Re-run iMessage pairing for any approved business conversations after the identity switch.

## OpenClaw Notes

- Runtime source of truth: `~/.openclaw/openclaw.json`
- Workspace mirror: `/Users/mmm/Downloads/yhack/.openclaw/openclaw.json`
- iMessage bridge path: `/Users/mmm/.local/bin/imsg`
- Keep both configs aligned if channel settings change.

## Why This Matters

- Keeps customer or business-owner conversations out of the owner's personal thread list
- Avoids identity confusion in iMessage
- Makes future deployment and access control cleaner
