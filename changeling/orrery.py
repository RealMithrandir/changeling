"""The Orrery — HTMX-powered monitoring dashboard."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from changeling import db

log = structlog.get_logger()

router = APIRouter(prefix="/orrery", tags=["orrery"])


def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: monospace; background: #0a0a0a; color: #c0c0c0; padding: 1rem; }}
        h1 {{ color: #00ff88; margin-bottom: 1rem; }}
        h2 {{ color: #00cc66; margin: 1rem 0 0.5rem; }}
        table {{ border-collapse: collapse; width: 100%; margin-bottom: 1rem; }}
        th, td {{ border: 1px solid #333; padding: 0.4rem 0.6rem; text-align: left; }}
        th {{ background: #1a1a1a; color: #00ff88; }}
        tr:nth-child(even) {{ background: #111; }}
        .hostile {{ color: #ff4444; font-weight: bold; }}
        .named_ai {{ color: #ffaa00; }}
        .trusted {{ color: #00ff88; }}
        .foxfire {{ color: #ff00ff; }}
        .badge {{ padding: 0.1rem 0.4rem; border-radius: 3px; font-size: 0.85em; }}
        .refresh-hint {{ color: #666; font-size: 0.85em; margin-bottom: 1rem; }}
    </style>
</head>
<body>
    <h1>&#x2689; The Orrery</h1>
    <p class="refresh-hint">Auto-refreshes every 5s</p>
    {body}
</body>
</html>"""


def _sessions_table(sessions: list[dict[str, Any]]) -> str:
    if not sessions:
        return "<p>No sessions yet.</p>"
    rows = ""
    for s in sessions:
        cls = s["agent_class"]
        css = cls if cls in ("hostile", "named_ai", "trusted") else ""
        fox = " &#x1f525;" if s["foxfire_tripped"] else ""
        rows += (
            f"<tr>"
            f"<td class='{css}'>{cls}{fox}</td>"
            f"<td>{s['ip']}</td>"
            f"<td>{s['user_agent'][:60]}</td>"
            f"<td>{s['request_count']}</td>"
            f"<td>{s['mutation_count']}</td>"
            f"<td>{s['first_seen']}</td>"
            f"<td>{s['last_seen']}</td>"
            f"</tr>"
        )
    return f"""<table>
<tr><th>Class</th><th>IP</th><th>User-Agent</th><th>Requests</th><th>Mutations</th><th>First Seen</th><th>Last Seen</th></tr>
{rows}
</table>"""


def _events_table(events: list[dict[str, Any]]) -> str:
    if not events:
        return "<p>No events yet.</p>"
    rows = ""
    for e in events:
        css = "foxfire" if e["event_type"] == "foxfire_trip" else ""
        rows += (
            f"<tr class='{css}'>"
            f"<td>{e['created_at']}</td>"
            f"<td>{e['event_type']}</td>"
            f"<td>{e.get('ip', '')}</td>"
            f"<td>{e.get('path', '')}</td>"
            f"<td>{e.get('detail', '')[:80]}</td>"
            f"</tr>"
        )
    return f"""<table>
<tr><th>Time</th><th>Event</th><th>IP</th><th>Path</th><th>Detail</th></tr>
{rows}
</table>"""


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> str:
    database = await db.get_db()
    try:
        sessions = await db.get_sessions(database)
        events = await db.get_events(database)
    finally:
        await database.close()

    body = f"""
    <div hx-get="/orrery/partials/sessions" hx-trigger="every 5s" hx-swap="innerHTML">
        <h2>Active Sessions</h2>
        {_sessions_table(sessions)}
    </div>
    <div hx-get="/orrery/partials/events" hx-trigger="every 5s" hx-swap="innerHTML">
        <h2>Event Log</h2>
        {_events_table(events)}
    </div>
    """
    return _page("The Orrery — Changeling", body)


@router.get("/partials/sessions", response_class=HTMLResponse)
async def sessions_partial(request: Request) -> str:
    database = await db.get_db()
    try:
        sessions = await db.get_sessions(database)
    finally:
        await database.close()
    return f"<h2>Active Sessions</h2>\n{_sessions_table(sessions)}"


@router.get("/partials/events", response_class=HTMLResponse)
async def events_partial(request: Request) -> str:
    database = await db.get_db()
    try:
        events = await db.get_events(database)
    finally:
        await database.close()
    return f"<h2>Event Log</h2>\n{_events_table(events)}"
