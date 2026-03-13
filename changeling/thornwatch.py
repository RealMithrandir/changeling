"""The Thornwatch — agent classification by headers and behavior."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from starlette.requests import Request

from changeling.grimoire import Grimoire

log = structlog.get_logger()

# Headers typically present in real browsers but absent in scrapers
BROWSER_HEADERS = {"accept-language", "sec-fetch-mode", "sec-ch-ua"}


@dataclass
class Classification:
    agent_class: str  # "trusted", "named_ai", "hostile", "unknown", "human"
    action: str  # "pass" | "mutate"
    reason: str


def classify(request: Request, grimoire: Grimoire) -> Classification:
    """Classify an incoming request based on headers and the Grimoire."""
    ua = request.headers.get("user-agent", "")

    # No user-agent at all → suspicious
    if not ua:
        return Classification("unknown", "mutate", "missing user-agent")

    # Check grimoire agent rules
    # Trusted
    trusted = grimoire.agents.get("trusted")
    if trusted:
        for pattern in trusted.user_agents:
            if pattern.lower() in ua.lower():
                return Classification("trusted", "pass", f"trusted: {pattern}")

    # Named AI
    named = grimoire.agents.get("named_ai")
    if named:
        for pattern in named.user_agents:
            if pattern.lower() in ua.lower():
                return Classification(
                    "named_ai", named.action, f"named_ai: {pattern}"
                )

    # Header heuristics — if it looks like a bot (missing browser headers)
    present = {h.lower() for h in request.headers.keys()}
    browser_signals = present & BROWSER_HEADERS
    if len(browser_signals) == 0 and "python" in ua.lower():
        return Classification("hostile", "mutate", "bot heuristic: no browser headers")

    if len(browser_signals) == 0 and "bot" in ua.lower():
        return Classification("hostile", "mutate", "bot heuristic: bot in UA")

    # Default: assume human
    return Classification("human", "pass", "default: human")
