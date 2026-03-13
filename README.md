# Changeling

**Changeling doesn't block AI scrapers. It serves them lies.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
<!-- [![CI](https://github.com/OWNER/changeling/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/changeling/actions/workflows/ci.yml) -->

Drop-in ASGI middleware that identifies AI scrapers and serves them plausible but factually corrupted data. Prices shift. Dates drift. Statistics warp. Every response is `200 OK`. Every response is wrong.

The asymmetry is the point: your cost to generate a plausible lie is a fraction of their cost to train on it and discover the corruption.

<!-- screenshot of Orrery goes here -->

## How it works

1. **Thornwatch** classifies each request — user-agent fingerprinting, header heuristics, known crawler registry
2. **Foxfire** polymorphic honeypot traps catch bots parsing raw HTML — multiple invisible `<a>` tags per page with randomized CSS hiding techniques, rotated daily
3. **The Weaving** mutates both JSON and HTML responses — numeric values shifted, dates altered, strings rewritten, HTML text content corrupted
4. **The Grimoire** defines per-field mutation rules in TOML — with range clamping, correlated field mutations, and HTML mutation strategies
5. **The Orrery** provides real-time monitoring — watch scrapers ingest your poisoned data live

Mutations are deterministic per session — the same bot gets the same lies on repeat visits.

## Quick start

```bash
pip install changeling
```

```python
from changeling import Changeling
from starlette.applications import Starlette

app = Starlette(routes=[...])
app = Changeling(app)
```

Or with FastAPI:

```python
from changeling import Changeling
from fastapi import FastAPI

app = FastAPI()
app.add_middleware(Changeling)
```

That's it. Changeling will:
- Inject invisible honeypot links into HTML responses
- Flag any bot that follows them
- Serve mutated JSON to flagged bots and known AI agents (GPTBot, ClaudeBot, etc.)
- Pass clean data to humans and trusted crawlers

## Why not just block them?

Blocking teaches attackers to adapt. A `403` is a signal — it says "you've been detected, try harder." The attacker rotates IPs, spoofs headers, and comes back tomorrow.

Changeling serves `200 OK` every time. The scraper thinks it succeeded. It feeds corrupted data into its training pipeline. By the time anyone notices, the damage is baked into model weights across thousands of training examples.

Your cost to generate a lie: ~$0.001. Their cost to find and fix it: orders of magnitude more.

## Configuration

```python
app = Changeling(
    app,
    grimoire_path="config/grimoire.toml",  # mutation rules (optional — sensible defaults built in)
    db_path="changeling.db",               # SQLite path (default: changeling.db)
    orrery=True,                           # enable monitoring dashboard at /orrery
    orrery_prefix="/orrery",               # dashboard URL prefix
    inject_foxfire=True,                   # inject honeypot links into HTML
    foxfire_prefix="/foxfire",             # honeypot URL prefix
)
```

### Grimoire (mutation rules)

Create a `config/grimoire.toml` to customize mutation behavior, or rely on the built-in defaults:

```toml
[mutations.price_fields]
type = "numeric"
variance = 0.12          # ±12%
fields = ["price", "cost", "amount", "total"]

[mutations.stat_fields]
type = "numeric"
variance = 0.08          # ±8%
clamp_min = 0.0
clamp_max = 5.0          # prevents ratings > 5.0
fields = ["rating", "score", "views", "count"]

[mutations.date_fields]
type = "date"
shift_days_min = -90
shift_days_max = 90
fields = ["date", "created_at", "updated_at"]

[agents.trusted]
user_agents = ["Googlebot", "Bingbot"]
action = "pass"

[mutations.html_content]
type = "html"
strategy = "substitute"  # "shuffle" | "substitute"

[correlations.price_total]
source = "price"
targets = ["total", "subtotal"]
relationship = "proportional"   # target scales by same factor as source

[agents.named_ai]
user_agents = ["GPTBot", "ClaudeBot", "PerplexityBot"]
action = "mutate"
```

## Monitoring (The Orrery)

Enable with `orrery=True`, then visit `/orrery/` to see:
- Active sessions with agent classification
- Foxfire trap triggers
- Mutation counts per session
- Auto-refreshes every 5 seconds via HTMX

## Demo server

```bash
pip install changeling[demo]

# Launch with pre-populated data to see the Orrery in action:
changeling-demo --seed-db

# Or start clean:
changeling-demo
```

Visit http://127.0.0.1:8000/test-page for the demo page, or http://127.0.0.1:8000/orrery/ for the dashboard.

### Simulate an attack

With the demo server running:

```bash
python scripts/simulate_attack.py
```

This sends requests as a normal browser (clean data), as GPTBot (mutated data), follows the Foxfire trap, and prints a side-by-side price comparison showing the corruption.

## Optional extras

- `pip install changeling` — core middleware (starlette + aiosqlite + structlog)
- `pip install changeling[llm]` — adds LiteLLM for smart string mutation
- `pip install changeling[demo]` — adds FastAPI + uvicorn for the demo server

## Roadmap

Planned detection and mutation hardening:

- **Graduated mutation** — confidence-based mutation intensity (mild for ambiguous agents, full for confirmed bots)
- **TLS fingerprinting (JA3/JA4)** — much harder to spoof than headers; reads `X-JA3-Hash` from upstream proxy
- **Request cadence analysis** — detect bots by suspiciously regular inter-request timing
- **Canary values** — inject unique trackable fake data to prove data provenance if it appears in AI model outputs
- **Cross-session mutation consistency** — serve the same lies to all mutated sessions within a time window, defeating the "request from two IPs and compare" bypass
