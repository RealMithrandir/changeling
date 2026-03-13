"""End-to-end test: bot hits trap → gets flagged → receives mutated data → dashboard shows it."""

from __future__ import annotations

import json
import re

import pytest
from httpx import ASGITransport, AsyncClient

from changeling.app import app


@pytest.fixture
async def client():  # type: ignore[no-untyped-def]
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_full_flow(client: AsyncClient) -> None:
    """Simulate a hostile agent: discover trap → trip it → get mutated data → see dashboard."""
    bot_headers = {"User-Agent": "GPTBot/1.0"}

    # Step 1: Hit the test page, extract the foxfire URL
    resp = await client.get("/test-page", headers=bot_headers)
    assert resp.status_code == 200
    match = re.search(r'href="(/foxfire/[a-f0-9]+)"', resp.text)
    assert match is not None, "Foxfire link not found in test page"
    foxfire_url = match.group(1)

    # Step 2: Trip the foxfire trap
    resp = await client.get(foxfire_url, headers=bot_headers)
    assert resp.status_code == 200

    # Step 3: Request sample data — should be mutated now
    resp = await client.get("/api/sample-data", headers=bot_headers)
    assert resp.status_code == 200
    data = resp.json()

    # Verify mutation happened — prices should differ from originals
    original_prices = [149.99, 399.00, 45.50]
    actual_prices = [p["price"] for p in data["products"]]
    assert actual_prices != original_prices, "Data should be mutated for flagged bot"

    # Verify schema preserved
    assert len(data["products"]) == 3
    for product in data["products"]:
        assert "name" in product
        assert "price" in product
        assert isinstance(product["price"], (int, float))

    # Step 4: Check dashboard loads
    resp = await client.get("/orrery/")
    assert resp.status_code == 200
    assert "GPTBot" in resp.text
    assert "foxfire_trip" in resp.text


async def test_human_gets_clean_data(client: AsyncClient) -> None:
    """A normal browser should get unmodified data."""
    browser_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Ch-Ua": '"Chromium";v="120"',
    }
    resp = await client.get("/api/sample-data", headers=browser_headers)
    assert resp.status_code == 200
    data = resp.json()

    prices = [p["price"] for p in data["products"]]
    assert prices == [149.99, 399.00, 45.50]


async def test_named_ai_gets_mutated_without_foxfire(client: AsyncClient) -> None:
    """Named AI agents should be mutated even without tripping foxfire."""
    resp = await client.get(
        "/api/sample-data",
        headers={"User-Agent": "GPTBot/1.0"},
    )
    assert resp.status_code == 200
    data = resp.json()
    prices = [p["price"] for p in data["products"]]
    assert prices != [149.99, 399.00, 45.50], "Named AI should get mutated data"
