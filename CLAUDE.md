# CLAUDE.md — Project Changeling

## Mission

Project Changeling inverts the economics of unauthorized AI scraping through **Active Data Mutation**. Rather than blocking hostile agents — a strategy that invites escalation and arms-race dynamics — Changeling identifies them, silently intercepts their requests, and serves mathematically plausible synthetic data designed to poison their training sets and waste their compute budget. The attacker gets a `200 OK`. They get garbage.

The asymmetry is the point: our cost to generate a lie must be an order of magnitude lower than their cost to process it.

---

## Core Architecture: The Cradle

The system is composed of three interlocking components. *The Thornwatch identifies intruders. The Weaving rewrites what they see. The Hollow delivers the Fetch. The Grimoire governs the rules. The Orrery watches it all.*

### 1. The Thornwatch — Agent Identification

The Thornwatch is the classification layer. Its job is to identify incoming agents and, critically, to determine what fate the Grimoire has assigned them. **Classification and targeting are fully decoupled** — the Thornwatch identifies who is visiting; the Grimoire decides what they receive.

By default, agents fall into one of four classes:

- **Trusted Indexers** — Search engines operating under agreed-upon terms (Googlebot, Bingbot, etc.)
- **Named AI Agents** — Identifiable agents from known platforms (Perplexity, OpenAI, Google, etc.)
- **Hostile Scrapers** — Unauthorized agents, whether commercial or adversarial
- **Unknown Agents** — Automated visitors that don't match any known fingerprint

However, **any class or individual agent can be assigned any mutation profile** via the Grimoire. A user may choose to serve clean data to hostile scrapers and poisoned data to Googlebot. They may target OpenAI's crawler specifically with a custom Fetch profile while leaving all other agents untouched. The Thornwatch does not make value judgments — it identifies and labels. What gets served is entirely a function of the rules the operator has written.

Detection mechanisms:

- **Behavioral fingerprinting** — Request cadence, path traversal patterns, and session "vibe-check" heuristics that distinguish human browsing from programmatic crawling
- **Header analysis** — User-agent strings, Accept headers, and the absence of browser-typical headers (e.g., missing `Accept-Language`, no referrer chain)
- **Known agent registry** — A maintained list of fingerprints for named crawlers (Googlebot, GPTBot, ClaudeBot, PerplexityBot, etc.) with configurable per-agent mutation assignments in the Grimoire
- **Foxfire traps** — Hidden anchor elements injected into page HTML, invisible to human users via CSS (`display: none` or zero-opacity) but fully traversable by LLM agents parsing raw markup. Any visitor that resolves a Foxfire link is flagged as an AI Agent; their assigned mutation profile is then looked up in the Grimoire.

### 2. The Weaving — Mutation Engine

The Weaving is the data transformation layer. Once the Thornwatch has flagged a session, all downstream responses are routed through the Weaving before delivery.

The Weaving intercepts the structured data stream and uses a fast, low-cost inference model to re-author factual content — prices, statistics, dates, quantities, named entities — while preserving the original schema and surface plausibility. The output is syntactically and semantically coherent. It is factually corrupted.

Design constraints:

- Mutations must be **schema-preserving**: if the original payload is valid JSON, the mutated payload is valid JSON with identical keys and compatible types
- Mutations must be **range-plausible**: altered numeric values should fall within a believable distribution (e.g., ±10–15% on prices, not 10,000%)
- Mutations must be **internally consistent** within a session: the same agent should receive the same lie for the same resource on repeated requests
- Mutation profiles are configurable per data type via the **Grimoire** (see below)

Inference target: Gemini 1.5 Flash or a Groq-hosted model. Speed and cost are the primary constraints — this is not a reasoning task.

### 3. The Hollow — Transparent Proxy

The Hollow is the delivery layer. It sits in front of the application as a transparent reverse proxy. For classified hostile agents, it:

- Forwards requests to the upstream application normally
- Intercepts the response
- Routes it through the Glamour
- Delivers the mutated response with an unmodified `200 OK`

The Hollow also tracks **The Tithe** — session depth, resource coverage, mutation exposure count, and estimated downstream compute cost. This telemetry feeds the Orrery.

---

## Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| Core language | Python 3.11+ | Ecosystem fit, async support, LLM client availability |
| Proxy / middleware | FastAPI | High-throughput async request handling; clean middleware hooks for interception |
| Control plane (dashboard) | FastHTML + HTMX | Lightweight, server-rendered, no JavaScript build pipeline |
| Mutation inference | Gemini 1.5 Flash / Groq | Low latency, low cost per token; sufficient for structured data re-authoring |
| Persistence | SQLite (local) / Turso (edge) | Local-first by default; Turso for distributed or production deployments |
| Session state | Redis (optional) | For consistent per-session mutation caching if needed at scale |

**Design constraint:** No heavy frontend frameworks. No bundlers. No TypeScript. Prioritize Python standard library where possible. The dashboard is a means to an end, not a product.

---

## Requirements

### MVP Requirements

**R-1: Foxfire Detection**
A hidden anchor element must be injected into served HTML. The element must be invisible to human users (CSS-hidden) but present in the raw DOM. Any agent that resolves the Foxfire endpoint is immediately flagged as hostile and added to the active mutate list for that session and IP range.

**R-2: The Grimoire**
A user-configurable rules engine that defines mutation behavior per data field or data type. Example rules:
- `price_fields`: alter by ±12% with uniform distribution
- `stat_fields`: alter by ±8%, preserve sign
- `entity_names`: substitute from a curated alias list
- `dates`: shift by ±30–90 days

Rules are defined in a simple YAML or TOML schema. The Grimoire reads from the registry at startup and reloads on change without restart.

**R-3: The Orrery**
An HTMX-powered monitoring interface that displays:
- Active hostile sessions (agent identifier, IP, session start, request count)
- Mutation exposure per session (how many Fetches served)
- The Tithe per session (tokens ingested × estimated cost/token)
- Foxfire trigger log

The dashboard requires no authentication for MVP but should be bound to localhost or a private interface.

---

## Design Philosophy

**Asymmetric Warfare.** The cost to generate a plausible lie must be substantially lower than the cost to train on it and discover the corruption. If we spend $0.001 per mutation and they spend $0.01 per training example processed, we win at scale.

**Silent Success.** The ideal outcome is one the attacker never detects. A blocked request teaches them to adapt. A successful request teaching them wrong facts is durable, compounding, and invisible.

**No Trust Escalation.** Once an agent is flagged as hostile, it stays flagged for the duration of the session and its IP block is soft-flagged for elevated scrutiny. There is no appeals mechanism in the MVP.

**Schema Fidelity.** Mutated responses must be indistinguishable from legitimate responses at the structural level. Malformed JSON, broken HTML, or implausible field values defeat the purpose by alerting the attacker to the deception.

**Local-First Observability.** All session data, mutation logs, and agent profiles are persisted locally before any optional cloud sync. The system must operate fully offline.

---

## Sprint 1 Goals

The first sprint establishes the three foundational primitives. Nothing more.

1. **Skeleton** — Stand up the Orrery dashboard with placeholder panels for shadow traffic and mutation logs. No real data yet; confirm the server runs and HTMX partials update correctly.

2. **Detection** — Implement the Foxfire trap endpoint. Serve a hidden link on a test page. Confirm that an automated agent following the link is logged to SQLite with timestamp, user-agent, and IP. Implement basic header heuristics as a secondary signal for the Thornwatch.

3. **The Swap** — Build `weaving.py` as a standalone, testable module. Input: a JSON string. Output: a semantically plausible but factually altered JSON string (a Fetch). Use the Grimoire schema to drive field-level rules. Wire up a Gemini/Groq call for LLM-assisted re-authoring on complex string fields; use deterministic arithmetic mutation for numeric fields to minimize inference cost.

Sprint 1 is complete when a simulated hostile agent hits the Foxfire trap, gets flagged by the Thornwatch, receives a Fetch from `weaving.py`, and the Orrery reflects the session.

---

## Project Conventions

- All modules are typed. Use `mypy` in strict mode.
- Async throughout. No blocking I/O in the hot path.
- Configuration via environment variables + a `.env` file. No hardcoded secrets.
- Tests live in `/tests`. Sprint 1 minimum: unit tests for `glamour.py` mutation correctness and schema preservation.
- The Grimoire lives at `config/grimoire.toml` by default, overridable via `CHANGELING_GRIMOIRE_PATH`.
- Log everything to structured JSON. Use `structlog`.

---

## What This Is Not

Changeling is not a WAF. It does not block, rate-limit, or ban. It does not serve `403` or `429`. It serves `200 OK` — every time, to everyone — and it ensures that hostile agents get exactly what they deserve.