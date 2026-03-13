"""The Weaving — mutate JSON data to produce a Fetch (plausible lie)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
from datetime import datetime, timedelta
from typing import Any

import structlog

from changeling.grimoire import Grimoire, MutationRule

log = structlog.get_logger()

LLM_MODEL = os.environ.get("CHANGELING_LLM_MODEL", "")


def _seed_for(session_key: str, field_path: str) -> int:
    """Deterministic seed from session identity + field path."""
    h = hashlib.sha256(f"{session_key}:{field_path}".encode()).digest()
    return int.from_bytes(h[:4], "big")


def mutate_numeric(
    value: float | int, rule: MutationRule, rng: random.Random
) -> float | int:
    """Apply numeric mutation within the rule's variance, then clamp."""
    factor = 1.0 + rng.uniform(-rule.variance, rule.variance)
    result = value * factor

    # Apply clamping if configured
    if rule.clamp_min is not None:
        result = max(result, rule.clamp_min)
    if rule.clamp_max is not None:
        result = min(result, rule.clamp_max)

    # Preserve type
    if isinstance(value, int):
        return int(round(result))
    return round(result, 2)


def _compute_factor(
    value: float | int, rule: MutationRule, rng: random.Random
) -> float:
    """Compute the mutation factor for a numeric field (for correlation support)."""
    return 1.0 + rng.uniform(-rule.variance, rule.variance)


def _apply_factor(
    value: float | int, factor: float, rule: MutationRule | None
) -> float | int:
    """Apply a pre-computed factor to a numeric value, with optional clamping."""
    result = value * factor
    if rule is not None:
        if rule.clamp_min is not None:
            result = max(result, rule.clamp_min)
        if rule.clamp_max is not None:
            result = min(result, rule.clamp_max)
    if isinstance(value, int):
        return int(round(result))
    return round(result, 2)


def mutate_date(value: str, rule: MutationRule, rng: random.Random) -> str:
    """Shift a date string by a random number of days."""
    # Try common date formats
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(value, fmt)
            shift = rng.randint(rule.shift_days_min, rule.shift_days_max)
            shifted = dt + timedelta(days=shift)
            return shifted.strftime(fmt)
        except ValueError:
            continue
    # Can't parse — return as-is
    return value


async def mutate_string_llm(
    key: str, value: str, rng: random.Random
) -> str:
    """Use LLM to generate a plausible replacement for a string field."""
    if not LLM_MODEL:
        # No LLM configured — simple deterministic substitution
        return _deterministic_string_mutate(value, rng)
    try:
        import litellm

        response = await litellm.acompletion(
            model=LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a data mutation engine. Given a field name and value, "
                        "return a single plausible but different replacement value. "
                        "Return ONLY the replacement value, nothing else."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Field: {key}\nValue: {value}",
                },
            ],
            max_tokens=100,
            temperature=0.7,
        )
        result: str = response.choices[0].message.content.strip()
        return result
    except Exception:
        log.warning("weaving.llm_failed", key=key, exc_info=True)
        return _deterministic_string_mutate(value, rng)


def _deterministic_string_mutate(value: str, rng: random.Random) -> str:
    """Simple deterministic string mutation — shuffle words, swap chars."""
    if not value:
        return value
    words = value.split()
    if len(words) > 1:
        rng.shuffle(words)
        return " ".join(words)
    # Single word: reverse it with some char swaps
    chars = list(value)
    if len(chars) > 2:
        i = rng.randint(0, len(chars) - 2)
        chars[i], chars[i + 1] = chars[i + 1], chars[i]
    return "".join(chars)


def _is_numeric_string(value: str) -> bool:
    """Check if a string looks like a number."""
    try:
        float(value)
        return True
    except ValueError:
        return False


async def weave(
    data: str,
    grimoire: Grimoire,
    session_key: str,
) -> str:
    """Mutate a JSON string according to Grimoire rules.

    Args:
        data: JSON string to mutate
        grimoire: loaded Grimoire rules
        session_key: unique key for session (IP:UA hash) for deterministic seeding

    Returns:
        Mutated JSON string preserving schema
    """
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        log.warning("weaving.invalid_json")
        return data

    # Dict to propagate correlation factors: source_field_lower -> factor
    correlation_factors: dict[str, float] = {}
    mutated = await _mutate_value(
        parsed, grimoire, session_key, "", correlation_factors
    )
    return json.dumps(mutated, ensure_ascii=False)


async def _mutate_value(
    value: Any,
    grimoire: Grimoire,
    session_key: str,
    path: str,
    correlation_factors: dict[str, float],
) -> Any:
    """Recursively mutate a value based on its key and type."""
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            new_path = f"{path}.{k}" if path else k
            result[k] = await _mutate_field(
                k, v, grimoire, session_key, new_path, correlation_factors
            )
        return result
    elif isinstance(value, list):
        return [
            await _mutate_value(
                item, grimoire, session_key, f"{path}[{i}]",
                correlation_factors,
            )
            for i, item in enumerate(value)
        ]
    return value


async def _mutate_field(
    key: str,
    value: Any,
    grimoire: Grimoire,
    session_key: str,
    path: str,
    correlation_factors: dict[str, float],
) -> Any:
    """Mutate a single field based on Grimoire rules."""
    rule = grimoire.rule_for_field(key)

    if rule is None or not rule.enabled:
        # No rule or disabled rule for this field — recurse if compound, else pass through
        if isinstance(value, (dict, list)):
            return await _mutate_value(
                value, grimoire, session_key, path, correlation_factors
            )
        return value

    seed = _seed_for(session_key, path)
    rng = random.Random(seed)

    if rule.type == "numeric" and isinstance(value, (int, float)):
        # Check if this field is a correlation target
        corr = grimoire.correlation_for_target(key)
        if corr is not None:
            source_lower = corr.source.lower()
            if source_lower in correlation_factors:
                # Apply the source's factor instead of an independent mutation
                return _apply_factor(
                    value, correlation_factors[source_lower], rule
                )

        # Compute factor; store it if this field is a correlation source
        factor = _compute_factor(value, rule, rng)
        if grimoire.is_correlation_source(key):
            correlation_factors[key.lower()] = factor

        result = value * factor
        # Apply clamping
        if rule.clamp_min is not None:
            result = max(result, rule.clamp_min)
        if rule.clamp_max is not None:
            result = min(result, rule.clamp_max)
        if isinstance(value, int):
            return int(round(result))
        return round(result, 2)

    if rule.type == "date" and isinstance(value, str):
        return mutate_date(value, rule, rng)

    if rule.type == "string" and isinstance(value, str):
        return await mutate_string_llm(key, value, rng)

    # Type mismatch — recurse or pass through
    if isinstance(value, (dict, list)):
        return await _mutate_value(
            value, grimoire, session_key, path, correlation_factors
        )
    return value
