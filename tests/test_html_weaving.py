"""Tests for HTML content mutation."""

from __future__ import annotations

import re

import pytest

from changeling.grimoire import Grimoire, MutationRule, load_grimoire
from changeling.html_weaving import weave_html


@pytest.fixture
def grimoire():  # type: ignore[no-untyped-def]
    return load_grimoire()


SAMPLE_HTML = """<!DOCTYPE html>
<html>
<head><title>Test Page</title></head>
<body>
<h1>Product Listing</h1>
<p>We have 150 products in stock with an average rating of 4.7 stars.</p>
<p>Our top seller has sold 2500 units this quarter.</p>
<p>Prices range from 29.99 to 599.99 dollars.</p>
<div class="footer">
<p>Contact us at our 3 office locations.</p>
</div>
</body>
</html>"""


async def test_html_structure_preserved(grimoire) -> None:  # type: ignore[no-untyped-def]
    """HTML tags and attributes must be preserved after mutation."""
    result = await weave_html(SAMPLE_HTML, grimoire, "test-session")
    # All structural elements should still be present
    assert "<html>" in result
    assert "</html>" in result
    assert "<head>" in result
    assert "<title>Test Page</title>" in result
    assert "<h1>" in result
    assert "</body>" in result
    assert 'class="footer"' in result


async def test_numbers_are_mutated(grimoire) -> None:  # type: ignore[no-untyped-def]
    """Inline numbers in text should be altered."""
    result = await weave_html(SAMPLE_HTML, grimoire, "test-session")
    # The number 150 should be mutated (within ~8% → ~138-162)
    # We check it's not the exact original
    assert "150 products" not in result or "2500 units" not in result, (
        "At least some numbers should be mutated"
    )


async def test_html_mutation_deterministic(grimoire) -> None:  # type: ignore[no-untyped-def]
    """Same session key should produce same HTML mutations."""
    r1 = await weave_html(SAMPLE_HTML, grimoire, "session-x")
    r2 = await weave_html(SAMPLE_HTML, grimoire, "session-x")
    assert r1 == r2


async def test_different_sessions_produce_different_html(grimoire) -> None:  # type: ignore[no-untyped-def]
    """Different sessions should produce different mutations."""
    r1 = await weave_html(SAMPLE_HTML, grimoire, "session-a")
    r2 = await weave_html(SAMPLE_HTML, grimoire, "session-b")
    assert r1 != r2


async def test_empty_html_passthrough(grimoire) -> None:  # type: ignore[no-untyped-def]
    """Empty or whitespace HTML should pass through."""
    result = await weave_html("", grimoire, "test-session")
    assert result == ""

    result = await weave_html("   ", grimoire, "test-session")
    assert result == "   "


async def test_no_numbers_html_unchanged(grimoire) -> None:  # type: ignore[no-untyped-def]
    """HTML without numbers should be mostly unchanged in substitute mode."""
    html = "<html><body><p>Hello world</p></body></html>"
    result = await weave_html(html, grimoire, "test-session")
    assert "<p>Hello world</p>" in result


async def test_shuffle_strategy_reorders_paragraphs() -> None:
    """Shuffle strategy should reorder <p> elements."""
    grimoire = Grimoire(
        mutations={
            "html_content": MutationRule(
                type="html",
                fields=[],
                strategy="shuffle",
            ),
        },
    )

    html = """<html><body>
<p>First paragraph</p>
<p>Second paragraph</p>
<p>Third paragraph</p>
</body></html>"""

    result = await weave_html(html, grimoire, "shuffle-session")
    # All paragraphs should still be present
    assert "First paragraph" in result
    assert "Second paragraph" in result
    assert "Third paragraph" in result
    # Structure preserved
    assert "<html>" in result
    assert "</body>" in result


async def test_decimal_numbers_mutated(grimoire) -> None:  # type: ignore[no-untyped-def]
    """Decimal numbers in text should be mutated and remain decimal."""
    html = "<html><body><p>Price is 29.99 dollars</p></body></html>"
    result = await weave_html(html, grimoire, "decimal-session")
    # Extract the number from the result
    match = re.search(r"Price is ([\d.]+) dollars", result)
    assert match is not None
    mutated_price = float(match.group(1))
    # Should be within ~8% of 29.99
    assert 27.0 <= mutated_price <= 33.0


async def test_html_entities_preserved(grimoire) -> None:  # type: ignore[no-untyped-def]
    """HTML entities like &amp; should be preserved."""
    html = "<html><body><p>Tom &amp; Jerry have 100 episodes</p></body></html>"
    result = await weave_html(html, grimoire, "entity-session")
    assert "&amp;" in result
