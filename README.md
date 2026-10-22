# Tabula

> **Rebuild in progress.** The product is being re-scoped to purchasing operations for small retailers (POS → replenishment plan → existing-supplier PO → receiving → invoice match). Work is tracked in [docs/CHECKPOINTS.md](docs/CHECKPOINTS.md). The sections below describe the original hackathon system, which stays as legacy/demo code.

## Tabula API (new core)

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
createdb tabula_dev && createdb tabula_test
DATABASE_URL=postgresql+psycopg://localhost/tabula_dev .venv/bin/alembic upgrade head
TABULA_AUTH_MODE=dev .venv/bin/uvicorn clawbot.api.app:app --reload   # docs at /docs
.venv/bin/pytest                                                       # runs against tabula_test
```

Layout: `clawbot/api/app.py` (single app) · `clawbot/api/v1/` (routers) · `clawbot/domain/` (tenant-scoped services: inventory ledger, outbox, audit, connector events) · `clawbot/persistence/` (SQLAlchemy models + Alembic migrations).

In dev auth mode send `X-Dev-User: you@example.com`; every tenant-scoped call also needs `X-Tenant-Id`, which the server checks against your membership. Stock changes require an `Idempotency-Key` header. Dev auth is accepted only with `TABULA_ENV=development|test` and only from loopback clients without `X-Forwarded-For`.

### Browser flow (owner app)

```bash
(cd demo-ui && npm install)
scripts/dev.sh            # migrates, starts API :8080, import / connector / PO workers, UI :5173
scripts/restart_api.sh    # restart only the API after backend changes (same dev settings)
```

Open http://127.0.0.1:5173/signup and create an account (email + password, 10+ characters). Then:

1. **Store details** — name, what you sell, time zone, currency → **Set up your store**: a checklist (stock file, sales history, suppliers and prices, delivery address); each step says what it unlocks. Stores that are set up open straight on **Overview**.
2. **Overview** — what is short, what to order (suggested quantity, cases, estimated cost, supplier — from the same plan engine, not saved) and what is on the way with expected dates; missing data shows the next step instead of a number. **Review reorder plan** is the main button.
3. **Inventory** — search, filter, sort; an item opens in a side panel (barcode, suppliers and cost, sales, expected stock, changes, orders). **Scan** is the main button: pick the work mode (look up / stock in / sold or used / damaged / count), scan, confirm the quantity; each change shows before → after and can be undone. USB/Bluetooth scanners and typing work; camera where the browser supports it. Square-owned stock is read-only here.
4. **Orders** — *Needs review / In progress / Done* with amount, status, expected arrival and the next step; *Suppliers* is a tab here. The reorder plan turns into one draft per supplier with your quantities; the order page shows items, cost and delivery first and folds the calculation, the kept email and the audit trail away.
5. **Insights** — sales trend, period comparison (per day with data), best and slow sellers, expected stockouts.
6. **Settings** — store details and delivery address, **Data sources** (Excel/CSV, shared Google Sheets link, Square: demo connection until Sandbox settings exist, see `docs/SQUARE_SETUP.md`), **Team**.

- **Test mode**: an approved order is kept in Tabula as a test message and never emailed. No payments.
- **Sample store**: on "Your stores", *Create a sample store* builds a fictional pet shop owned by your account and marked as a sample everywhere.
- **Team**: Settings › Team → Invite gives the owner a one-time sign-up link to pass on (Tabula doesn't send email yet); without it nobody can sign up with that address.
- Email-only **demo sign-in** exists only with `TABULA_AUTH_MODE=dev` on this machine (loopback); `TABULA_AUTH_MODE=password` turns it off. Not yet: email verification, password reset.
- Browser walkthroughs (screenshots, `PLAYWRIGHT_CHANNEL=chrome` uses the installed Chrome):
  - `scripts/ui_walkthrough_owner.py` — sign up → setup with own files → Overview → inventory panel → scan → insights → supplier → reorder plan → draft → approve (`docs/screenshots/owner-app/`)
  - `scripts/ui_walkthrough.py` — order → supplier reply → receiving (`docs/screenshots/cp7/`; seeds its own demo store)
  - `scripts/ui_walkthrough_store.py` — sample store, export-order matching, Square (demo) receiving check (`docs/screenshots/store-readiness/`)
- Square Sandbox: settings and the one-command check in `docs/SQUARE_SETUP.md` §6 (`scripts/square_sandbox_check.py`).
- Real customer data: `docs/CUSTOMER_DATA_REQUEST.md` (what to ask for, `clawbot.devtools.anonymize`, `clawbot.devtools.compare_orders`). No customer data has been used yet.

Tabula is a multi-agent commerce intelligence platform for small business operators. It has two interconnected subsystems:

1. **Agentic Marketplace** — a privacy-preserving coordination layer where independent stores share anonymized demand signals, debate market trends via AI agents, and receive personalized recommendations — without ever exposing their private inventory to competitors.

2. **Commerce Agent Network** — per-store AI agents that handle inventory monitoring, procurement sourcing, trend analysis, and price discovery, all accessible over iMessage or CLI.

---

## Agentic Marketplace

### Concept

Small, competing stores each run a local AI agent. Overnight, those agents generate demand signals from their inventory. The signals are anonymized before being shared with a coordinator agent, which synthesizes market trends. Stores then receive personalized recommendations derived from the collective intelligence — without any store's raw data being visible to another.

The core privacy guarantee: the coordinator sees aggregated, noise-injected, shuffled signals with store identifiers stripped. Individual store reasoning and inventory never leave the local agent context.

### Five-phase overnight pipeline

```
Phase 1 — Signal Generation
  Each store's PersonalAgent analyzes local inventory under scenario multipliers
  → 10 demand signals per store (category, direction, intensity, confidence, reasoning)
  → Each store's signal batch hashed and committed to Solana devnet

Phase 2 — Anonymization
  Anonymizer strips store IDs
  Adds Gaussian noise (σ = 0.05) to intensity and confidence values
  Shuffles signal order to obscure per-store patterns
  → AnonymizedSignal objects with random signal_id

Phase 3 — Aggregation and Debate
  CoordinatorAgent (Nous Hermes 4 70B) synthesizes per-category AggregatedTrends
  → category, direction, strength, signal_count, consensus score
  3-round agent debate: each store's agent argues about the aggregated trends
  (Agents receive only anonymized trends — no store IDs revealed during debate)
  → debate_log.json

Phase 3.75 — Ecosystem Analytics (optional)
  HexAnalytics computes: overall health score, consensus strength, signal diversity,
  anomaly detection (z-score > 2σ), collaboration value (% improvement from sharing)
  If Hex API is configured, triggers a Hex notebook run with ecosystem data
  → ecosystem_health.json

Phase 4 — Recommendation Generation
  Each PersonalAgent receives aggregated trends + its own local context
  → 3–5 prioritized actions per store (increase_stock / reduce_stock / promote / hold / discontinue)
  → store_{id}_recommendations.json

Phase 5 — Output and Verification
  Full cycle data written to results.json
  Debate summary hashed and committed to Solana
  VerificationReport written to verification.json
```

### Agent debate

After aggregation, each store's agent participates in a structured debate over three rounds. In each round, every agent receives the aggregated market trends and the prior round's arguments, then produces a 2–3 sentence response — agreeing, disagreeing, or adding local nuance. Agents may not reveal their private inventory or store-identifying numbers; they may only reason from the shared aggregated signal.

The debate does not produce a winner. It surfaces divergent perspectives (e.g., local context that macro trends miss, skepticism about signal quality) before recommendations are finalized. The full transcript is replayed in the frontend as a group chat.

```python
# Temperature by task
SIGNAL_TEMPERATURE        = 0.3   # factual signal generation
RECOMMENDATION_TEMPERATURE = 0.7  # recommendations
DEBATE_TEMPERATURE         = 0.8  # debate (more opinionated)
DEBATE_ROUNDS              = 3
```

### Solana verification

`coordination/solana_verifier.py` commits SHA-256 hashes of market data to Solana devnet via the SPL Memo Program. Two commit types:

- **Signal commits** — after Phase 1, each store's signal batch is hashed and committed with label `signals:{store_id}`
- **Summary commit** — after debate/aggregation, the full summary (cycle ID, trend count, all trends) is hashed and committed with label `debate_summary`

If the `solders` / `solana` libraries are unavailable, the system runs in hash-only mode — hashes are computed and stored locally but not submitted on-chain. The `VerificationReport` records which commits succeeded and whether `all_verified` is true.

Output in `verification.json`:
```json
{
  "chain": "solana",
  "network": "devnet",
  "signals_on_chain": true,
  "signal_count": 5,
  "signals": [{ "data_hash": "...", "label": "signals:store_a", "tx_signature": "...", "verified": true }],
  "summary_on_chain": true,
  "summary": { "data_hash": "...", "label": "debate_summary", ... },
  "all_verified": true
}
```

### Stores and scenarios

Five stores are configured, each with inventory across 10 product categories:

| ID | Store | Category |
|---|---|---|
| store_a | College Convenience & Deli | grocery, beverages, snacks |
| store_b | Grails | sneakers, streetwear |
| store_c | Edible Arrangements | gifts, seasonal |
| store_d | Tinaliah Designs | jewelry, accessories |
| store_e | The Marketa | artisan goods, handmade crafts |

Scenarios adjust per-category demand multipliers applied during signal generation:

- `default` — 1.0× across all categories
- `holiday_rush` — 2.2–3.5× for gifts, seasonal, electronics
- `new_trend` — 2.8× for clothing/accessories, 2.5× for handmade crafts

### Running the pipeline

```bash
cd YHack_2026/agentic-marketplace
python main.py --scenario holiday_rush
python main.py --scenario default --verbose    # logs full API transcripts
python main.py --scenario new_trend --chat     # generates group chat simulation
```

Required environment variables:

```
NOUS_API_KEY          # Nous Research inference API (Hermes model)
SOLANA_RPC_URL        # Default: Solana devnet
SOLANA_PRIVATE_KEY    # Optional — required for on-chain commits
HEX_API_KEY           # Optional — for ecosystem analytics notebook runs
```

### Output files

All written to `YHack_2026/agentic-marketplace/output/`:

| File | Contents |
|---|---|
| `results.json` | Full cycle: trends, per-store recommendations, verification, ecosystem health |
| `market_trends.json` | Aggregated trends only |
| `store_{id}_recommendations.json` | Per-store action list |
| `debate_log.json` | Full debate transcript (all rounds, all participants) |
| `debate_summary.json` | Compact summary: top rising/falling, average confidence, key recommendations |
| `verification.json` | Solana commit records with tx signatures |
| `ecosystem_health.json` | Hex analytics: health score, anomalies, collaboration value |
| `conversation_log.json` | API transcripts (requires `--verbose`) |
| `group_chat.json` | Chat simulation (requires `--chat`) |

---

## Commerce Agent Network

The per-store agent layer handles day-to-day operations: inventory monitoring, supplier sourcing, demand trend analysis, and price monitoring. Interaction is via iMessage or CLI.

### Agents

**Universal Agent** (`clawbot/agents/universal_agent.py`)

Primary entry point for reactive and proactive flows. Receives a plain-language iMessage, decides which domain agents to invoke, collects their outputs, and composes a reply. Can also send unprompted digests when inventory, price, or trend conditions warrant it.

**Orchestrator Agent** (`clawbot/agents/orchestrator_agent.py`)

Handles multi-step flows: extracts product intent from a message, validates demand via the Trend Agent, adds the item to the procurement queue, sources suppliers, and sends a formatted purchase order summary over iMessage.

**Trend Agent** (`clawbot/agents/trend_agent.py`)

Runs a tool loop against multiple demand signal sources per category and synthesizes them into a `TrendReport` with status (`trending` / `stable` / `fading`), supporting signals, per-SKU recommendations, and end-of-trend warnings. Informed by `recommendation_memory.py`, which tracks which categories the owner acts on and adjusts future recommendation weighting accordingly.

**Procurement Agent** (`clawbot/agents/procurement_agent.py`)

Queries the active procurement list from MongoDB, runs supplier searches via Google Custom Search (configured for B2B results), records quotes, and compares them against the known supplier catalog for margin viability. Outputs a ranked supplier list and per-line margin analysis.

**Inventory Agent** (`clawbot/agents/inventory_agent.py`)

Reads stock levels and transaction history from MongoDB. Identifies items below reorder threshold and resolves product metadata from barcodes via UPC lookup. Low-stock items are automatically surfaced to the Procurement Agent during digest runs.

**Price Discovery Agent** (`clawbot/agents/price_discovery_agent.py`)

Manages a watchlist of supplier prices. When a new scan is recorded, `WatchMonitorWorkflow` calculates savings against the baseline, checks a per-item cooldown, and triggers an iMessage alert if the threshold is met.

### Data sources

| Source | What it provides | Integration |
|---|---|---|
| Google Trends | Interest-over-time by keyword and region | `pytrends` |
| Reddit | Post volume, sentiment, top discussions per category | `praw` |
| Google Custom Search | B2B supplier results with pricing signals | `GOOGLE_API_KEY` + CSE ID |
| UPC Item DB / Go-UPC | Product metadata from barcode | `GO_UPC_API_KEY` |
| Browserbase / Playwright | Live page scraping (store catalog, supplier pages) | `BROWSERBASE_API_KEY` |
| Store sales history | Top SKUs, seasonality, historical performance | MongoDB |
| macOS Messages (`chat.db`) | Inbound iMessage polling | SQLite read |

### Storage

**MongoDB** collections:

| Collection | Contents |
|---|---|
| `inventory` | SKUs, quantities, reorder thresholds, cost/sell price |
| `stock_transactions` | Append-only log of stock movements |
| `procurement_items` | Products queued for sourcing |
| `supplier_quotes` | Discovered quotes with price, MOQ, URL, confidence |
| `known_suppliers` | Existing vendor relationships |
| `supplier_catalog` | Product costs and target margins per supplier |

**JSON files** (`.openclaw/price-scout/`): `watchlist.json`, `findings.json`, `alerts.json`, `settings.json`, `session-memory.json`

**Recommendation memory** (`.openclaw/trend-agent/recommendation_memory.json`): per-category preference scores derived from owner action history, injected into the Trend Agent system prompt, auto-aged after 7 days.

### Data flow

**Trend analysis**
```
TrendRequest (business, location, categories, optional store URL)
  ├── scrape_store_inventory()   → existing product catalog
  ├── get_google_trends()        → interest curve per category
  ├── get_reddit_trends()        → social signal per category
  ├── get_local_events()         → upcoming demand drivers
  └── get_sales_history()        → historical performance

Claude synthesizes → TrendReport { status, signals, recommendations[], end_of_trend_warning }
  └── recommendation_memory.record_recommendations()
```

**Procurement**
```
add_procurement_item() or ingest_low_stock()
  └── Procurement Agent tool loop:
        get_procurement_list()
        for each item → search_suppliers() → record_quote()
        get_quotes()
  └── generate_order_form()
        match quotes against supplier_catalog
        compute margin per line
  └── ProcurementOrder → iMessage
```

**Price monitoring**
```
Owner adds watch (baseline: supplier + price + threshold)
  └── record_scan(ScanInput)
        WatchMonitorWorkflow:
          savings_pct = (baseline - found) / baseline
          if savings_pct ≥ threshold AND cooldown elapsed → Alert → iMessage
```

### Setup

**Requirements:** Python 3.10+, MongoDB, macOS (for iMessage)

```bash
pip install -r requirements.txt
```

Copy `.openclaw/.env.example` to `.openclaw/.env`:

```
ANTHROPIC_API_KEY=...          # Required

MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=clawbot

# Optional
GOOGLE_API_KEY=...
GOOGLE_SEARCH_ENGINE_ID=...
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
GO_UPC_API_KEY=...
BROWSERBASE_API_KEY=...
```

Seed MongoDB:
```bash
python -m clawbot.tools.seed_mongodb
```

iMessage integration requires Full Disk Access for Terminal in System Settings > Privacy & Security.

### CLI usage

```bash
# Price monitoring
python -m clawbot.main list-watch
python -m clawbot.main add-watch --name "2000ct Mailers NJ" --baseline-supplier "Vendor" --baseline-price 1.15 --threshold 0.05
python -m clawbot.main record-scan --watch-id mailers-2000-nj --supplier "AltVendor" --price 1.08 --url "https://..."
python -m clawbot.main summary

# Trend analysis
python trend_cli.py --business "Mike's Hardware" --location "Austin, TX" --categories "power tools,fasteners"

# Procurement
python procurement_cli.py --item "nitrile gloves" --qty 500

# Inventory
python inventory_cli.py scan --barcode 012345678901
python inventory_cli.py low-stock

# iMessage digest
python imsg_cli.py send --business "Mike's Hardware" --location "Austin, TX" --recipient "+15551234567"

# Local API
python -m clawbot.main serve-api --port 8000
```

API endpoints: `GET /health`, `GET /watchlist`, `GET /findings`, `GET /alerts`, `GET /summary`, `POST /message/send`

---

## Frontend

The dashboard (`demo-ui/`) visualizes both subsystems:

| Page | Route | Content |
|---|---|---|
| Dashboard | `/dashboard` | Featured recommendation, inventory health chart, live debate chat |
| Agentic Simulation | `/agentic-simulation` | Animated 7-phase pipeline visualization with per-store business plans |
| Inventory | `/inventory` | Live MongoDB inventory with search, stock bars, reorder indicators |
| Orders | `/orders` | Action queue — all recommendations sorted by priority |
| Trends | `/trends` | Trending product cards with supplier info and AI picks |
| Signal Ledger | `/sales-history` | All market trends with direction, strength, consensus, store action count |
| Price Scout | `/price-scout` | Browserbase live view for price scanning sessions |

The simulation page animates the marketplace pipeline: stores on a map → form a circle → encryption animation (scrambled text, key exchange) → aggregation core → feedback phase. Clicking a store in the recommendation phase opens a sidebar with the store's AI-generated business plan.

```bash
cd demo-ui
npm install
npm run dev
```

---

## Project structure

```
YHack_2026/agentic-marketplace/
├── main.py                          # CLI entry point (--scenario, --verbose, --chat)
├── config.py                        # Model settings, scenarios, store definitions
├── generate_summary.py              # Compacts results.json → debate_summary.json
├── agents/
│   └── personal_agent.py            # Per-store agent: signals, debate, recommendations
├── coordination/
│   ├── overnight_pipeline.py        # 5-phase orchestration loop
│   └── solana_verifier.py           # SHA-256 hashing + Solana devnet commits
└── output/                          # Generated JSON files

clawbot/
├── agents/                          # Universal, Orchestrator, Trend, Procurement, Inventory, Price
├── api/                             # ThreadingHTTPServer + routes
├── config/                          # AppPaths
├── memory/                          # Session notes
├── schemas/                         # Pydantic models
├── tools/                           # External API wrappers + MongoDB helpers
├── workflows/                       # WatchMonitorWorkflow, daily_ops
└── main.py                          # CLI subcommands

demo-ui/
└── src/
    ├── pages/                        # DashboardPage, AgentsPage, InventoryPage, etc.
    ├── simulation/                   # Animated pipeline visualization
    ├── components/                   # Shared UI components
    └── data.ts                       # Transforms JSON outputs for display
```

---

## Agent tool loop pattern

Every agent (in both subsystems) follows the same structure: a system prompt scoping its domain, a set of Python-backed tool definitions passed to the model API, and a dispatch loop that runs until the model reaches `end_turn`. Tool results are returned as `tool_result` messages. Agents do not share context — each runs an independent reasoning loop and returns structured output (Pydantic models or JSON) to the calling layer.

Adding a new data source means writing a tool function, registering it in the relevant agent's tool list, and describing it in the system prompt. The model handles invocation timing and result synthesis within the existing loop.
