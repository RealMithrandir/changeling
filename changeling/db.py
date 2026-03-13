"""Database layer — SQLite via aiosqlite."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

log = structlog.get_logger()

DB_PATH = Path(os.environ.get("CHANGELING_DB_PATH", "changeling.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ip          TEXT NOT NULL,
    user_agent  TEXT NOT NULL,
    agent_class TEXT NOT NULL DEFAULT 'unknown',
    first_seen  TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen   TEXT NOT NULL DEFAULT (datetime('now')),
    request_count INTEGER NOT NULL DEFAULT 0,
    mutation_count INTEGER NOT NULL DEFAULT 0,
    foxfire_tripped INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sessions_ip_ua ON sessions(ip, user_agent);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    event_type  TEXT NOT NULL,
    path        TEXT,
    detail      TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
"""


async def get_db(path: str | Path | None = None) -> aiosqlite.Connection:
    """Open (or create) the database and ensure schema exists.

    *path* overrides the default ``DB_PATH`` / env-var location.
    """
    target = Path(path) if path is not None else DB_PATH
    db = await aiosqlite.connect(str(target))
    db.row_factory = aiosqlite.Row
    await db.executescript(_SCHEMA)
    await db.commit()
    return db


async def get_or_create_session(
    db: aiosqlite.Connection,
    ip: str,
    user_agent: str,
    agent_class: str = "unknown",
) -> int:
    """Find existing session by IP+UA or create a new one. Returns session id."""
    cursor = await db.execute(
        "SELECT id FROM sessions WHERE ip = ? AND user_agent = ?",
        (ip, user_agent),
    )
    row = await cursor.fetchone()
    if row:
        session_id: int = row[0]
        await db.execute(
            "UPDATE sessions SET last_seen = datetime('now'), "
            "request_count = request_count + 1 WHERE id = ?",
            (session_id,),
        )
        await db.commit()
        return session_id

    cursor = await db.execute(
        "INSERT INTO sessions (ip, user_agent, agent_class, request_count) "
        "VALUES (?, ?, ?, 1)",
        (ip, user_agent, agent_class),
    )
    await db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


async def flag_foxfire(db: aiosqlite.Connection, session_id: int) -> None:
    """Mark a session as having tripped the Foxfire trap."""
    await db.execute(
        "UPDATE sessions SET foxfire_tripped = 1, agent_class = 'hostile' "
        "WHERE id = ?",
        (session_id,),
    )
    await db.commit()


async def increment_mutations(db: aiosqlite.Connection, session_id: int) -> None:
    """Increment mutation count for a session."""
    await db.execute(
        "UPDATE sessions SET mutation_count = mutation_count + 1 WHERE id = ?",
        (session_id,),
    )
    await db.commit()


async def add_event(
    db: aiosqlite.Connection,
    session_id: int,
    event_type: str,
    path: str = "",
    detail: str = "",
) -> None:
    """Log an event against a session."""
    await db.execute(
        "INSERT INTO events (session_id, event_type, path, detail) "
        "VALUES (?, ?, ?, ?)",
        (session_id, event_type, path, detail),
    )
    await db.commit()


async def get_sessions(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    """Return all sessions, most recent first."""
    cursor = await db.execute(
        "SELECT * FROM sessions ORDER BY last_seen DESC LIMIT 100"
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_events(
    db: aiosqlite.Connection, limit: int = 100
) -> list[dict[str, Any]]:
    """Return recent events."""
    cursor = await db.execute(
        "SELECT e.*, s.ip, s.user_agent FROM events e "
        "JOIN sessions s ON e.session_id = s.id "
        "ORDER BY e.created_at DESC LIMIT ?",
        (limit,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]
