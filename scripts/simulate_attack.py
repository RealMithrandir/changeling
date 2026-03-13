#!/usr/bin/env python3
"""Simulate an AI scraping attack against a running Changeling demo server.

Usage:
    python scripts/simulate_attack.py [--base-url http://127.0.0.1:8000]

Requires: pip install httpx
"""

from __future__ import annotations

import argparse
import json
import re
import sys

import httpx

# ── Headers ──────────────────────────────────────────────────────────

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Ch-Ua": '"Chromium";v="120", "Google Chrome";v="120"',
}

GPTBOT_HEADERS = {
    "User-Agent": "Mozilla/5.0 AppleWebKit/537.36 (compatible; GPTBot/1.2; +https://openai.com/gptbot)",
    "Accept": "application/json",
}

UNKNOWN_BOT_HEADERS = {
    "User-Agent": "DataHarvester/3.1 research-crawler",
    "Accept": "application/json",
}


def _print_header(text: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {text}")
    print(f"{'─' * 60}\n")


def _print_products(data: dict[str, object], label: str) -> list[tuple[str, float]]:
    """Print product prices and return (name, price) pairs."""
    products = data.get("products", [])
    pairs: list[tuple[str, float]] = []
    for p in products:  # type: ignore[union-attr]
        assert isinstance(p, dict)
        name = p["name"]
        price = p["price"]
        pairs.append((str(name), float(price)))
        print(f"  {label}  {name}: ${price}")
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate an AI scraping attack")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Base URL of the Changeling demo server",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    client = httpx.Client(timeout=10)

    # ── Step 1: Normal browser request ───────────────────────────────

    _print_header("Step 1: Normal browser request → clean data")
    resp = client.get(f"{base}/api/sample-data", headers=BROWSER_HEADERS)
    if resp.status_code != 200:
        print(f"  ERROR: got {resp.status_code}")
        sys.exit(1)
    clean = resp.json()
    clean_prices = _print_products(clean, "[clean]")
    print(f"\n  Status: {resp.status_code} OK — clean data served to human visitor")

    # ── Step 2: GPTBot request → mutated data ────────────────────────

    _print_header("Step 2: GPTBot request → mutated data")
    resp = client.get(f"{base}/api/sample-data", headers=GPTBOT_HEADERS)
    mutated = resp.json()
    mutated_prices = _print_products(mutated, "[mutated]")
    print(f"\n  Status: {resp.status_code} OK — GPTBot got plausible lies")

    # ── Step 3: Follow the Foxfire trap ──────────────────────────────

    _print_header("Step 3: Follow the Foxfire honeypot trap")
    print("  Fetching /test-page to find the hidden trap link...")
    resp = client.get(f"{base}/test-page", headers=UNKNOWN_BOT_HEADERS)
    html = resp.text

    # Extract the foxfire link
    match = re.search(r'href="(/foxfire/[a-f0-9]+)"', html)
    if not match:
        print("  WARNING: No Foxfire link found in HTML — is inject_foxfire enabled?")
    else:
        trap_url = match.group(1)
        print(f"  Found hidden link: {trap_url}")
        resp = client.get(f"{base}{trap_url}", headers=UNKNOWN_BOT_HEADERS)
        print(f"  Visited trap link → {resp.status_code} OK")
        print("  Agent is now flagged as hostile!")

    # ── Step 4: Unknown bot after Foxfire ─────────────────────────────

    _print_header("Step 4: Unknown bot request (post-Foxfire) → mutated data")
    resp = client.get(f"{base}/api/sample-data", headers=UNKNOWN_BOT_HEADERS)
    post_foxfire = resp.json()
    _print_products(post_foxfire, "[mutated]")
    print(f"\n  Status: {resp.status_code} OK — flagged agent gets mutated data")

    # ── Step 5: Side-by-side comparison ──────────────────────────────

    _print_header("Step 5: Side-by-side comparison")
    print(f"  {'Product':<30} {'Real Price':>12} {'GPTBot Got':>12} {'Diff':>8}")
    print(f"  {'─' * 30} {'─' * 12} {'─' * 12} {'─' * 8}")
    for (name, real), (_, fake) in zip(clean_prices, mutated_prices):
        diff_pct = ((fake - real) / real) * 100
        print(f"  {name:<30} ${real:>10.2f} ${fake:>10.2f} {diff_pct:>+7.1f}%")

    print("\n  Every response was 200 OK. The scraper has no idea.\n")


if __name__ == "__main__":
    main()
