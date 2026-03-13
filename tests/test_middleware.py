"""Tests for the Changeling ASGI middleware wrapping a vanilla app."""

from __future__ import annotations

import json
import re

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route

from changeling.middleware import Changeling


# --- A plain vanilla app (no Changeling logic) ---

VANILLA_DATA = {
    "products": [
        {"name": "Widget", "price": 50.0, "rating": 4.0, "date": "2025-01-01"}
    ],
    "meta": {"total_products": 1},
}


async def html_page(request: Request) -> HTMLResponse:
    return HTMLResponse(
        "<html><head></head><body><h1>Hello</h1></body></html>"
    )


async def json_api(request: Request) -> JSONResponse:
    return JSONResponse(VANILLA_DATA)


async def plain_text(request: Request) -> PlainTextResponse:
    return PlainTextResponse("just text")


vanilla = Starlette(
    routes=[
        Route("/page", html_page),
        Route("/api/data", json_api),
        Route("/plain", plain_text),
    ]
)


# --- Fixtures ---

@pytest.fixture
def wrapped_app(tmp_path):  # type: ignore[no-untyped-def]
    """Wrap the vanilla app with Changeling middleware."""
    db_path = str(tmp_path / "mw_test.db")
    return Changeling(
        vanilla,
        db_path=db_path,
        orrery=True,
        inject_foxfire=True,
    )


@pytest.fixture
async def client(wrapped_app):  # type: ignore[no-untyped-def]
    transport = ASGITransport(app=wrapped_app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --- Tests ---

async def test_html_gets_foxfire_injected(client: AsyncClient) -> None:
    """HTML responses should have a foxfire trap link injected before </body>."""
    resp = await client.get(
        "/page",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en",
            "Sec-Fetch-Mode": "navigate",
        },
    )
    assert resp.status_code == 200
    assert "/foxfire/" in resp.text
    assert 'aria-hidden="true"' in resp.text
    # Original content preserved
    assert "<h1>Hello</h1>" in resp.text


async def test_bot_trips_foxfire_then_gets_mutated(client: AsyncClient) -> None:
    """A bot that trips foxfire should receive mutated JSON on subsequent requests."""
    bot_headers = {"User-Agent": "SomeBot/1.0"}

    # 1. Get HTML page — foxfire link should be present
    resp = await client.get("/page", headers=bot_headers)
    assert resp.status_code == 200
    match = re.search(r'href="(/foxfire/[a-f0-9]+)"', resp.text)
    assert match is not None, "Foxfire link not found in HTML"
    foxfire_url = match.group(1)

    # 2. Trip the foxfire trap
    resp = await client.get(foxfire_url, headers=bot_headers)
    assert resp.status_code == 200

    # 3. Get JSON — should be mutated now
    resp = await client.get("/api/data", headers=bot_headers)
    assert resp.status_code == 200
    data = resp.json()
    # Schema preserved
    assert "products" in data
    assert len(data["products"]) == 1
    assert "price" in data["products"][0]
    # Price should be mutated (original is 50.0)
    assert data["products"][0]["price"] != 50.0


async def test_browser_gets_clean_json(client: AsyncClient) -> None:
    """A normal browser should get unmodified JSON data."""
    browser_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Ch-Ua": '"Chromium";v="120"',
    }
    resp = await client.get("/api/data", headers=browser_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["products"][0]["price"] == 50.0


async def test_named_ai_gets_mutated_without_foxfire(client: AsyncClient) -> None:
    """Named AI agents (e.g. GPTBot) should get mutated data without needing foxfire."""
    resp = await client.get(
        "/api/data", headers={"User-Agent": "GPTBot/1.0"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["products"][0]["price"] != 50.0, "Named AI should get mutated data"


async def test_orrery_mounts_when_enabled(client: AsyncClient) -> None:
    """When orrery=True, the dashboard should be accessible."""
    resp = await client.get("/orrery/")
    assert resp.status_code == 200
    assert "The Orrery" in resp.text


async def test_orrery_not_mounted_when_disabled(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """When orrery=False, the dashboard path should 404."""
    app = Changeling(
        vanilla,
        db_path=str(tmp_path / "no_orrery.db"),
        orrery=False,
    )
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/orrery/")
        assert resp.status_code == 404


async def test_plain_text_passes_through(client: AsyncClient) -> None:
    """Non-HTML/JSON content should pass through unmodified."""
    resp = await client.get(
        "/plain",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en",
            "Sec-Fetch-Mode": "navigate",
        },
    )
    assert resp.status_code == 200
    assert resp.text == "just text"


async def test_foxfire_endpoint_returns_200(client: AsyncClient) -> None:
    """The foxfire trap endpoint should return 200 with innocuous content."""
    from changeling.foxfire import trap_path

    path = trap_path()
    resp = await client.get(path, headers={"User-Agent": "CrawlBot/1.0"})
    assert resp.status_code == 200
    assert "not currently available" in resp.text
