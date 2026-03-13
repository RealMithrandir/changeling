"""Tests for Foxfire trap generation and detection."""

from __future__ import annotations

from changeling.foxfire import (
    is_foxfire_path,
    trap_html_snippet,
    trap_html_snippets,
    trap_path,
)


def test_trap_path_is_stable() -> None:
    """Trap path should be consistent within the same time period."""
    p1 = trap_path()
    p2 = trap_path()
    assert p1 == p2
    assert p1.startswith("/foxfire/")


def test_trap_html_contains_path() -> None:
    """HTML snippet must contain the current trap path."""
    path = trap_path()
    snippet = trap_html_snippet()
    assert path in snippet
    assert 'aria-hidden="true"' in snippet


def test_is_foxfire_path_positive() -> None:
    """Current trap path should be recognized."""
    path = trap_path()
    assert is_foxfire_path(path) is True


def test_is_foxfire_path_negative() -> None:
    """Random paths should not match."""
    assert is_foxfire_path("/foxfire/deadbeef") is False
    assert is_foxfire_path("/other/path") is False


def test_polymorphic_snippet_has_hiding_style() -> None:
    """Snippet should use a CSS hiding technique (varies daily)."""
    snippet = trap_html_snippet()
    # Must have some style attribute for hiding
    assert 'style="' in snippet
    # Must have aria-hidden
    assert 'aria-hidden="true"' in snippet


def test_trap_html_snippets_returns_multiple() -> None:
    """trap_html_snippets should return the requested number of traps."""
    snippets = trap_html_snippets(count=3)
    assert len(snippets) == 3
    # All should contain the foxfire path
    path = trap_path()
    for s in snippets:
        assert path in s
        assert 'aria-hidden="true"' in s


def test_trap_html_snippets_use_different_techniques() -> None:
    """Multiple traps should use different CSS hiding techniques."""
    snippets = trap_html_snippets(count=2)
    # Extract style attributes
    import re

    styles = []
    for s in snippets:
        m = re.search(r'style="([^"]+)"', s)
        assert m is not None
        styles.append(m.group(1))
    # The two styles should be different
    assert styles[0] != styles[1], "Multiple traps should use different CSS techniques"


def test_trap_html_snippets_deterministic() -> None:
    """Same secret should produce same snippets."""
    s1 = trap_html_snippets(count=2, secret="test-secret")
    s2 = trap_html_snippets(count=2, secret="test-secret")
    assert s1 == s2


def test_different_secrets_produce_different_snippets() -> None:
    """Different secrets should produce different snippets."""
    s1 = trap_html_snippet(secret="secret-a")
    s2 = trap_html_snippet(secret="secret-b")
    # Paths will differ, and potentially style/text too
    assert s1 != s2
