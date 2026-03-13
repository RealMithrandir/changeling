"""Demo endpoints and CLI entry point for Changeling."""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from changeling.foxfire import trap_html_snippet

SAMPLE_DATA: dict[str, Any] = {
    "products": [
        {
            "name": "Wireless Headphones Pro",
            "price": 149.99,
            "rating": 4.7,
            "reviews": 2847,
            "manufacturer": "AudioTech Industries",
            "date": "2025-06-15",
        },
        {
            "name": "Smart Watch Ultra",
            "price": 399.00,
            "rating": 4.5,
            "reviews": 1293,
            "manufacturer": "ChronoSync Labs",
            "date": "2025-03-22",
        },
        {
            "name": "Portable Charger 20000mAh",
            "price": 45.50,
            "rating": 4.8,
            "reviews": 5621,
            "manufacturer": "PowerVault Co",
            "date": "2025-01-10",
        },
    ],
    "meta": {
        "total_products": 3,
        "updated_at": "2025-11-01T12:00:00Z",
        "source": "changeling-demo",
    },
}


async def test_page(request: Request) -> HTMLResponse:
    """Demo page with an embedded Foxfire trap link."""
    foxfire = trap_html_snippet()
    return HTMLResponse(
        f"""<!DOCTYPE html>
<html>
<head><title>Sample Page</title></head>
<body>
    <h1>Welcome to our data service</h1>
    <p>We provide high-quality market data and analytics.</p>
    <p>Check out our <a href="/api/sample-data">sample data API</a>.</p>
    {foxfire}
</body>
</html>"""
    )


async def sample_data(request: Request) -> JSONResponse:
    """Return sample data — mutation is handled by the middleware."""
    return JSONResponse(SAMPLE_DATA)


demo_routes = [
    Route("/test-page", test_page),
    Route("/api/sample-data", sample_data),
]


@dataclass
class _SeedSession:
    ip: str
    user_agent: str
    agent_class: str
    request_count: int
    mutation_count: int
    foxfire_tripped: int
    minutes_ago: int


_SEED_SESSIONS = [
    _SeedSession(
        ip="198.51.100.10",
        user_agent="Mozilla/5.0 AppleWebKit/537.36 (compatible; GPTBot/1.2; +https://openai.com/gptbot)",
        agent_class="hostile",
        request_count=47,
        mutation_count=47,
        foxfire_tripped=1,
        minutes_ago=12,
    ),
    _SeedSession(
        ip="203.0.113.44",
        user_agent="PerplexityBot/1.0; +https://perplexity.ai/perplexitybot",
        agent_class="named_ai",
        request_count=23,
        mutation_count=23,
        foxfire_tripped=0,
        minutes_ago=35,
    ),
    _SeedSession(
        ip="66.249.66.1",
        user_agent="Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        agent_class="trusted",
        request_count=12,
        mutation_count=0,
        foxfire_tripped=0,
        minutes_ago=50,
    ),
    _SeedSession(
        ip="45.33.32.156",
        user_agent="python-requests/2.31.0",
        agent_class="hostile",
        request_count=8,
        mutation_count=8,
        foxfire_tripped=0,
        minutes_ago=5,
    ),
    _SeedSession(
        ip="192.0.2.200",
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        agent_class="human",
        request_count=3,
        mutation_count=0,
        foxfire_tripped=0,
        minutes_ago=2,
    ),
]


def _seed_db(db_path: str) -> None:
    """Pre-populate the database with fake sessions for demo purposes."""
    # Use synchronous sqlite3 directly — this runs before the event loop starts.
    from changeling.db import _SCHEMA

    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)

    now = datetime.utcnow()

    for s in _SEED_SESSIONS:
        first_seen = now - timedelta(minutes=s.minutes_ago)
        last_seen = now - timedelta(minutes=1)
        cur = conn.execute(
            "INSERT INTO sessions "
            "(ip, user_agent, agent_class, first_seen, last_seen, "
            "request_count, mutation_count, foxfire_tripped) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                s.ip,
                s.user_agent,
                s.agent_class,
                first_seen.isoformat(sep=" ", timespec="seconds"),
                last_seen.isoformat(sep=" ", timespec="seconds"),
                s.request_count,
                s.mutation_count,
                s.foxfire_tripped,
            ),
        )
        session_id = cur.lastrowid

        # Generate events for this session
        if s.foxfire_tripped:
            conn.execute(
                "INSERT INTO events (session_id, event_type, path, detail, created_at) "
                "VALUES (?, 'foxfire_trip', '/foxfire/trap', 'Followed honeypot link', ?)",
                (session_id, first_seen.isoformat(sep=" ", timespec="seconds")),
            )

        event_type = "mutation_served" if s.mutation_count > 0 else "clean_served"
        # Add a handful of representative events (not all N — keep it readable)
        event_count = min(s.request_count, 5)
        for i in range(event_count):
            t = first_seen + timedelta(seconds=i * 30)
            conn.execute(
                "INSERT INTO events (session_id, event_type, path, detail, created_at) "
                "VALUES (?, ?, '/api/sample-data', ?, ?)",
                (
                    session_id,
                    event_type,
                    f"request {i + 1}",
                    t.isoformat(sep=" ", timespec="seconds"),
                ),
            )

    conn.commit()
    conn.close()
    print(f"Seeded {len(_SEED_SESSIONS)} demo sessions into {db_path}")


def main() -> None:
    """Run the demo server with Changeling middleware."""
    parser = argparse.ArgumentParser(description="Changeling demo server")
    parser.add_argument(
        "--seed-db",
        action="store_true",
        help="Pre-populate the database with fake sessions for demo",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on (default: 8000)",
    )
    args = parser.parse_args()

    import uvicorn
    from starlette.applications import Starlette

    from changeling.middleware import Changeling

    db_path = "changeling.db"

    if args.seed_db:
        _seed_db(db_path)

    inner = Starlette(routes=demo_routes)
    app = Changeling(inner, orrery=True, db_path=db_path)

    uvicorn.run(app, host="127.0.0.1", port=args.port)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
