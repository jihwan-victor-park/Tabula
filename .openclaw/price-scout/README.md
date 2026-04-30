# PriceScout State

This folder stores the structured state for continuous price discovery.

Files:

- `settings.json` - runtime knobs for alerts and monitoring
- `watchlist.json` - watched SKUs, baseline suppliers, thresholds, and search queries
- `findings.json` - latest discovered price findings per watched item
- `alerts.json` - alert history and suppression state
- `runs/` - optional run artifacts or snapshots

Principles:

- Files are the source of truth.
- `memory/` is the human-readable narrative layer.
- This state is for price discovery only, not procurement or outreach.
