"""The Grimoire — loads and serves mutation rules from TOML config."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

if sys.version_info >= (3, 12):
    import tomllib
else:
    import tomli as tomllib

log = structlog.get_logger()

DEFAULT_PATH = Path("config/grimoire.toml")

_DEFAULT_RAW: dict[str, Any] = {
    "mutations": {
        "price_fields": {
            "type": "numeric",
            "variance": 0.12,
            "distribution": "uniform",
            "enabled": True,
            "fields": ["price", "cost", "amount", "total", "subtotal", "fee"],
        },
        "stat_fields": {
            "type": "numeric",
            "variance": 0.08,
            "distribution": "uniform",
            "preserve_sign": True,
            "clamp_min": 0.0,
            "clamp_max": 5.0,
            "enabled": True,
            "fields": ["count", "rating", "score", "views", "downloads", "users"],
        },
        "date_fields": {
            "type": "date",
            "shift_days_min": -90,
            "shift_days_max": 90,
            "enabled": True,
            "fields": ["date", "created_at", "updated_at", "published", "timestamp"],
        },
        "entity_names": {
            "type": "string",
            "strategy": "llm",
            "enabled": True,
            "fields": ["name", "author", "company", "brand", "manufacturer"],
        },
    },
    "agents": {
        "trusted": {
            "user_agents": ["Googlebot", "Bingbot", "Slurp", "DuckDuckBot"],
            "action": "pass",
        },
        "named_ai": {
            "user_agents": [
                "GPTBot", "ChatGPT-User", "ClaudeBot", "PerplexityBot",
                "Google-Extended", "Bytespider", "CCBot",
            ],
            "action": "mutate",
        },
        "hostile": {
            "action": "mutate",
        },
    },
}


@dataclass
class MutationRule:
    type: str  # "numeric", "date", "string", "html"
    fields: list[str]
    variance: float = 0.0
    distribution: str = "uniform"
    preserve_sign: bool = False
    shift_days_min: int = 0
    shift_days_max: int = 0
    strategy: str = "deterministic"
    clamp_min: float | None = None
    clamp_max: float | None = None
    enabled: bool = True


@dataclass
class Correlation:
    """Ties a source field's mutation factor to one or more target fields."""
    source: str
    targets: list[str]
    relationship: str = "proportional"  # target scales by same factor as source


@dataclass
class AgentRule:
    user_agents: list[str] = field(default_factory=list)
    action: str = "pass"  # "pass" | "mutate"


@dataclass
class Grimoire:
    mutations: dict[str, MutationRule] = field(default_factory=dict)
    agents: dict[str, AgentRule] = field(default_factory=dict)
    correlations: list[Correlation] = field(default_factory=list)
    # Lookup: field name -> MutationRule
    field_index: dict[str, MutationRule] = field(default_factory=dict)
    # Lookup: target field name -> Correlation
    _correlation_targets: dict[str, Correlation] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._rebuild_correlation_index()

    def _rebuild_correlation_index(self) -> None:
        self._correlation_targets = {}
        for corr in self.correlations:
            for target in corr.targets:
                self._correlation_targets[target.lower()] = corr

    def rule_for_field(self, field_name: str) -> MutationRule | None:
        """Return the mutation rule that covers a given field name."""
        lower = field_name.lower()
        for key, rule in self.field_index.items():
            if key == lower:
                return rule
        return None

    def correlation_for_target(self, field_name: str) -> Correlation | None:
        """Return the correlation where this field is a target, if any."""
        return self._correlation_targets.get(field_name.lower())

    def is_correlation_source(self, field_name: str) -> bool:
        """Check if a field is the source of any correlation."""
        lower = field_name.lower()
        return any(c.source.lower() == lower for c in self.correlations)

    def action_for_ua(self, user_agent: str) -> str:
        """Return 'pass' or 'mutate' for a given user-agent string."""
        ua_lower = user_agent.lower()
        # Check trusted first
        trusted = self.agents.get("trusted")
        if trusted:
            for pattern in trusted.user_agents:
                if pattern.lower() in ua_lower:
                    return "pass"
        # Check named AI agents
        named = self.agents.get("named_ai")
        if named:
            for pattern in named.user_agents:
                if pattern.lower() in ua_lower:
                    return named.action
        return "pass"


def load_grimoire(path: Path | str | None = None) -> Grimoire:
    """Load the Grimoire from a TOML file, or use built-in defaults.

    Resolution order:
    1. Explicit *path* argument
    2. ``CHANGELING_GRIMOIRE_PATH`` environment variable
    3. ``config/grimoire.toml`` relative to cwd (if it exists)
    4. Built-in ``_DEFAULT_RAW`` fallback
    """
    if path is not None:
        config_path = Path(path)
    elif "CHANGELING_GRIMOIRE_PATH" in os.environ:
        config_path = Path(os.environ["CHANGELING_GRIMOIRE_PATH"])
    elif DEFAULT_PATH.exists():
        config_path = DEFAULT_PATH
    else:
        log.info("grimoire.loading", source="built-in defaults")
        return _parse(_DEFAULT_RAW)

    log.info("grimoire.loading", path=str(config_path))
    raw = tomllib.loads(config_path.read_text())
    return _parse(raw)


def _parse(raw: dict[str, Any]) -> Grimoire:
    g = Grimoire()

    for name, data in raw.get("mutations", {}).items():
        rule = MutationRule(
            type=data["type"],
            fields=data.get("fields", []),
            variance=data.get("variance", 0.0),
            distribution=data.get("distribution", "uniform"),
            preserve_sign=data.get("preserve_sign", False),
            shift_days_min=data.get("shift_days_min", 0),
            shift_days_max=data.get("shift_days_max", 0),
            strategy=data.get("strategy", "deterministic"),
            clamp_min=data.get("clamp_min"),
            clamp_max=data.get("clamp_max"),
            enabled=data.get("enabled", True),
        )
        g.mutations[name] = rule
        for f in rule.fields:
            g.field_index[f.lower()] = rule

    for name, data in raw.get("agents", {}).items():
        g.agents[name] = AgentRule(
            user_agents=data.get("user_agents", []),
            action=data.get("action", "pass"),
        )

    for name, data in raw.get("correlations", {}).items():
        corr = Correlation(
            source=data["source"],
            targets=data.get("targets", []),
            relationship=data.get("relationship", "proportional"),
        )
        g.correlations.append(corr)

    g._rebuild_correlation_index()

    log.info(
        "grimoire.loaded",
        mutation_rules=len(g.mutations),
        agent_rules=len(g.agents),
        correlations=len(g.correlations),
        indexed_fields=len(g.field_index),
    )
    return g
