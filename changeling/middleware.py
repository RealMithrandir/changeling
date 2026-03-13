"""Pure ASGI middleware — drop-in Changeling integration."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import structlog
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from changeling import db
from changeling.foxfire import (
    is_foxfire_path,
    trap_html_snippet,
    trap_html_snippets,
    trap_path,
)
from changeling.grimoire import Grimoire, load_grimoire
from changeling.html_weaving import weave_html
from changeling.thornwatch import classify
from changeling.weaving import weave

log = structlog.get_logger()

# Regex to find the first block-level tag where we can insert a trap
_FIRST_BLOCK_RE = re.compile(
    rb"(<(?:p|div|section|article|main)[^>]*>)", re.IGNORECASE
)


class Changeling:
    """ASGI middleware that identifies AI scrapers and serves them mutated data.

    Usage::

        from changeling import Changeling
        app.add_middleware(Changeling)
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        grimoire_path: str | Path | None = None,
        db_path: str | Path | None = None,
        orrery: bool = False,
        orrery_prefix: str = "/orrery",
        inject_foxfire: bool = True,
        foxfire_prefix: str = "/foxfire",
        foxfire_secret: str | None = None,
    ) -> None:
        self.app = app
        self.grimoire_path = grimoire_path
        self.db_path = db_path
        self.orrery_enabled = orrery
        self.orrery_prefix = orrery_prefix
        self.inject_foxfire = inject_foxfire
        self.foxfire_prefix = foxfire_prefix
        self.foxfire_secret = foxfire_secret

        self._grimoire: Grimoire | None = None
        self._orrery_app: ASGIApp | None = None

    # ------------------------------------------------------------------
    # ASGI interface
    # ------------------------------------------------------------------

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._handle_lifespan(scope, receive, send)
            return

        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")

        # Foxfire trap hit
        if is_foxfire_path(
            path, secret=self.foxfire_secret, prefix=self.foxfire_prefix
        ):
            await self._handle_foxfire(scope, receive, send)
            return

        # Orrery dashboard
        if self.orrery_enabled and path.startswith(self.orrery_prefix):
            if self._orrery_app is None:
                self._orrery_app = self._build_orrery_app()
            await self._orrery_app(scope, receive, send)
            return

        # Normal request — classify and maybe mutate
        await self._proxy(scope, receive, send)

    # ------------------------------------------------------------------
    # Lifespan
    # ------------------------------------------------------------------

    async def _handle_lifespan(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        async def wrapped_receive() -> Message:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await self._startup()
            return message

        async def wrapped_send(message: Message) -> None:
            if message["type"] == "lifespan.shutdown.complete":
                pass  # nothing to tear down currently
            await send(message)

        await self.app(scope, wrapped_receive, wrapped_send)

    async def _startup(self) -> None:
        self._grimoire = load_grimoire(self.grimoire_path)
        # Ensure DB schema exists
        database = await db.get_db(self.db_path)
        await database.close()
        log.info(
            "changeling.started",
            foxfire_path=trap_path(
                secret=self.foxfire_secret, prefix=self.foxfire_prefix
            ),
        )

    # ------------------------------------------------------------------
    # Foxfire trap handler
    # ------------------------------------------------------------------

    async def _handle_foxfire(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        request = Request(scope, receive, send)
        ip = _client_ip(request)
        ua = request.headers.get("user-agent", "unknown")
        log.warning("foxfire.tripped", ip=ip, user_agent=ua, path=scope["path"])

        database = await db.get_db(self.db_path)
        try:
            session_id = await db.get_or_create_session(database, ip, ua, "hostile")
            await db.flag_foxfire(database, session_id)
            await db.add_event(
                database, session_id, "foxfire_trip", scope["path"], f"UA: {ua}"
            )
        finally:
            await database.close()

        body = b"<html><body><p>Resource not currently available.</p></body></html>"
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    [b"content-type", b"text/html; charset=utf-8"],
                    [b"content-length", str(len(body)).encode()],
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    # ------------------------------------------------------------------
    # Main proxy path
    # ------------------------------------------------------------------

    async def _proxy(self, scope: Scope, receive: Receive, send: Send) -> None:
        grimoire = self._get_grimoire()
        request = Request(scope, receive, send)
        ip = _client_ip(request)
        ua = request.headers.get("user-agent", "unknown")

        classification = classify(request, grimoire)
        log.info(
            "request.classified",
            ip=ip,
            user_agent=ua[:60],
            agent_class=classification.agent_class,
            action=classification.action,
        )

        database = await db.get_db(self.db_path)
        try:
            session_id = await db.get_or_create_session(
                database, ip, ua, classification.agent_class
            )
            cursor = await database.execute(
                "SELECT foxfire_tripped FROM sessions WHERE id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()
            foxfire_tripped = row is not None and row[0] == 1
            should_mutate = classification.action == "mutate" or foxfire_tripped
        finally:
            await database.close()

        if should_mutate:
            await self._send_mutated(
                scope, receive, send, grimoire, ip, ua, session_id, request
            )
        elif self.inject_foxfire:
            await self._send_with_foxfire(scope, receive, send)
        else:
            await self.app(scope, receive, send)

    async def _send_mutated(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        grimoire: Grimoire,
        ip: str,
        ua: str,
        session_id: int,
        request: Request,
    ) -> None:
        """Buffer response; if JSON, mutate it. If HTML, mutate content and inject foxfire."""
        response_started = False
        initial_message: Message | None = None
        body_parts: list[bytes] = []
        content_type = b""

        async def buffered_send(message: Message) -> None:
            nonlocal response_started, initial_message, content_type
            if message["type"] == "http.response.start":
                initial_message = message
                response_started = True
                headers = dict(message.get("headers", []))
                content_type = headers.get(b"content-type", b"")
            elif message["type"] == "http.response.body":
                body_parts.append(message.get("body", b""))
                if not message.get("more_body", False):
                    pass  # will flush after app returns

        await self.app(scope, receive, buffered_send)

        full_body = b"".join(body_parts)
        ct = content_type.decode("utf-8", errors="replace").lower()

        if "application/json" in ct:
            session_key = f"{ip}:{ua}"
            try:
                mutated = await weave(
                    full_body.decode("utf-8"), grimoire, session_key
                )
                full_body = mutated.encode("utf-8")
            except Exception:
                log.warning("weaving.failed", exc_info=True)

            database = await db.get_db(self.db_path)
            try:
                await db.increment_mutations(database, session_id)
                await db.add_event(
                    database,
                    session_id,
                    "mutation_served",
                    scope.get("path", ""),
                    f"class={ua[:40]}",
                )
            finally:
                await database.close()
            log.info("weaving.served", session_id=session_id, ip=ip)
        elif "text/html" in ct and b"</body>" in full_body.lower():
            # Mutate HTML text content for hostile agents
            html_rule = grimoire.mutations.get("html_content")
            if html_rule is None or html_rule.enabled:
                session_key = f"{ip}:{ua}"
                try:
                    mutated_html = await weave_html(
                        full_body.decode("utf-8"), grimoire, session_key
                    )
                    full_body = mutated_html.encode("utf-8")
                except Exception:
                    log.warning("html_weaving.failed", exc_info=True)

            # Inject multiple foxfire traps
            if self.inject_foxfire:
                full_body = _inject_foxfire_traps(
                    full_body,
                    secret=self.foxfire_secret,
                    prefix=self.foxfire_prefix,
                )

            database = await db.get_db(self.db_path)
            try:
                await db.increment_mutations(database, session_id)
                await db.add_event(
                    database,
                    session_id,
                    "mutation_served",
                    scope.get("path", ""),
                    f"html_mutated ua={ua[:40]}",
                )
            finally:
                await database.close()
            log.info("html_weaving.served", session_id=session_id, ip=ip)

        # Rewrite content-length and send
        assert initial_message is not None
        headers = [
            (k, v)
            for k, v in initial_message.get("headers", [])
            if k != b"content-length"
        ]
        headers.append((b"content-length", str(len(full_body)).encode()))
        initial_message["headers"] = headers
        await send(initial_message)
        await send({"type": "http.response.body", "body": full_body})

    async def _send_with_foxfire(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        """Pass-through but inject foxfire into HTML responses."""
        initial_message: Message | None = None
        body_parts: list[bytes] = []
        content_type = b""

        async def buffered_send(message: Message) -> None:
            nonlocal initial_message, content_type
            if message["type"] == "http.response.start":
                initial_message = message
                headers = dict(message.get("headers", []))
                content_type = headers.get(b"content-type", b"")
            elif message["type"] == "http.response.body":
                body_parts.append(message.get("body", b""))

        await self.app(scope, receive, buffered_send)

        full_body = b"".join(body_parts)
        ct = content_type.decode("utf-8", errors="replace").lower()

        if "text/html" in ct and b"</body>" in full_body.lower():
            full_body = _inject_foxfire_traps(
                full_body,
                secret=self.foxfire_secret,
                prefix=self.foxfire_prefix,
            )

        assert initial_message is not None
        headers = [
            (k, v)
            for k, v in initial_message.get("headers", [])
            if k != b"content-length"
        ]
        headers.append((b"content-length", str(len(full_body)).encode()))
        initial_message["headers"] = headers
        await send(initial_message)
        await send({"type": "http.response.body", "body": full_body})

    # ------------------------------------------------------------------
    # Orrery sub-app
    # ------------------------------------------------------------------

    def _build_orrery_app(self) -> ASGIApp:
        from starlette.applications import Starlette
        from starlette.routing import Route

        from changeling.orrery import (
            _events_table,
            _page,
            _sessions_table,
        )

        db_path = self.db_path
        prefix = self.orrery_prefix

        async def dashboard(request: Request) -> Any:
            from starlette.responses import HTMLResponse

            database = await db.get_db(db_path)
            try:
                sessions = await db.get_sessions(database)
                events = await db.get_events(database)
            finally:
                await database.close()

            body = f"""
            <div hx-get="{prefix}/partials/sessions" hx-trigger="every 5s" hx-swap="innerHTML">
                <h2>Active Sessions</h2>
                {_sessions_table(sessions)}
            </div>
            <div hx-get="{prefix}/partials/events" hx-trigger="every 5s" hx-swap="innerHTML">
                <h2>Event Log</h2>
                {_events_table(events)}
            </div>
            """
            return HTMLResponse(_page("The Orrery — Changeling", body))

        async def sessions_partial(request: Request) -> Any:
            from starlette.responses import HTMLResponse

            database = await db.get_db(db_path)
            try:
                sessions = await db.get_sessions(database)
            finally:
                await database.close()
            return HTMLResponse(
                f"<h2>Active Sessions</h2>\n{_sessions_table(sessions)}"
            )

        async def events_partial(request: Request) -> Any:
            from starlette.responses import HTMLResponse

            database = await db.get_db(db_path)
            try:
                events = await db.get_events(database)
            finally:
                await database.close()
            return HTMLResponse(
                f"<h2>Event Log</h2>\n{_events_table(events)}"
            )

        routes = [
            Route(f"{prefix}/", dashboard),
            Route(f"{prefix}/partials/sessions", sessions_partial),
            Route(f"{prefix}/partials/events", events_partial),
        ]
        return Starlette(routes=routes)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_grimoire(self) -> Grimoire:
        if self._grimoire is None:
            self._grimoire = load_grimoire(self.grimoire_path)
        return self._grimoire


def _inject_foxfire_traps(
    body: bytes,
    *,
    secret: str | None,
    prefix: str,
) -> bytes:
    """Inject multiple foxfire traps into an HTML body.

    Places one trap before </body> and one after the first block-level tag.
    """
    snippets = trap_html_snippets(
        count=2, secret=secret, prefix=prefix
    )

    # Trap 1: after the first <p>, <div>, <section>, <article>, or <main> tag
    first_snippet = snippets[0].encode("utf-8")
    match = _FIRST_BLOCK_RE.search(body)
    if match:
        insert_pos = match.end()
        body = body[:insert_pos] + first_snippet + body[insert_pos:]

    # Trap 2: before </body> (the traditional position)
    second_snippet = snippets[1].encode("utf-8")
    body = body.replace(b"</body>", second_snippet + b"</body>")

    return body


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return "0.0.0.0"
