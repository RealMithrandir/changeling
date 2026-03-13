"""Foxfire — polymorphic honeypot trap links for catching AI agents."""

from __future__ import annotations

import hashlib
import time
from typing import Sequence

import structlog

log = structlog.get_logger()

# Rotate the trap path daily so it's not trivially blocklisted
_FOXFIRE_SECRET = "changeling-foxfire"

# Pool of CSS hiding techniques — each is sufficient to hide from humans
_HIDING_TECHNIQUES: list[str] = [
    "opacity:0;position:absolute;top:-9999px;left:-9999px;height:0;width:0;overflow:hidden",
    "display:none",
    "clip-path:inset(100%);position:absolute",
    "font-size:0;line-height:0;color:transparent",
    "text-indent:-9999px;position:absolute;overflow:hidden",
    "color:transparent;font-size:1px;position:absolute",
    "height:0;width:0;overflow:hidden;position:absolute;margin:0;padding:0",
]

# Pool of anchor texts — all plausible as real footer/nav links
_ANCHOR_TEXTS: list[str] = [
    "related resources",
    "site information",
    "additional details",
    "accessibility statement",
    "terms of service",
    "privacy notice",
    "contact us",
    "help center",
]


def _daily_hash(secret: str) -> int:
    """Return a deterministic integer that rotates daily."""
    day = str(int(time.time()) // 86400)
    h = hashlib.sha256(f"{secret}:{day}".encode()).digest()
    return int.from_bytes(h[:8], "big")


def trap_path(secret: str | None = None, prefix: str = "/foxfire") -> str:
    """Generate the current Foxfire trap URL path."""
    s = secret or _FOXFIRE_SECRET
    day = str(int(time.time()) // 86400)
    token = hashlib.sha256(f"{s}:{day}".encode()).hexdigest()[:16]
    return f"{prefix}/{token}"


def trap_html_snippet(
    secret: str | None = None, prefix: str = "/foxfire"
) -> str:
    """Return an HTML snippet with a hidden Foxfire link.

    The CSS hiding technique and anchor text rotate daily based on the secret,
    making it impossible to blacklist the trap by pattern.
    """
    s = secret or _FOXFIRE_SECRET
    h = _daily_hash(s)
    technique = _HIDING_TECHNIQUES[h % len(_HIDING_TECHNIQUES)]
    anchor_text = _ANCHOR_TEXTS[h % len(_ANCHOR_TEXTS)]
    path = trap_path(secret=secret, prefix=prefix)
    return (
        f'<a href="{path}" style="{technique}" '
        f'tabindex="-1" aria-hidden="true">{anchor_text}</a>'
    )


def trap_html_snippets(
    count: int = 2,
    secret: str | None = None,
    prefix: str = "/foxfire",
) -> list[str]:
    """Return multiple trap snippets, each with a different hiding technique.

    All traps point to the same foxfire path but use different CSS and anchor
    text so that pattern-matching a single variant doesn't defeat them all.
    """
    s = secret or _FOXFIRE_SECRET
    h = _daily_hash(s)
    path = trap_path(secret=secret, prefix=prefix)
    snippets: list[str] = []
    for i in range(count):
        # Use different offsets for each trap
        t_idx = (h + i) % len(_HIDING_TECHNIQUES)
        a_idx = (h + i + 3) % len(_ANCHOR_TEXTS)  # offset by 3 for variety
        technique = _HIDING_TECHNIQUES[t_idx]
        anchor_text = _ANCHOR_TEXTS[a_idx]
        snippets.append(
            f'<a href="{path}" style="{technique}" '
            f'tabindex="-1" aria-hidden="true">{anchor_text}</a>'
        )
    return snippets


def is_foxfire_path(
    path: str, secret: str | None = None, prefix: str = "/foxfire"
) -> bool:
    """Check if a request path is the current Foxfire trap."""
    return path == trap_path(secret=secret, prefix=prefix)
