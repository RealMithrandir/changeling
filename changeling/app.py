"""Changeling Demo — FastAPI app with Changeling middleware."""

from __future__ import annotations

import structlog
from fastapi import FastAPI

from changeling import Changeling
from changeling.demo import demo_routes

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
)

app = FastAPI(title="Changeling Demo", version="0.1.0")

# Mount demo endpoints
for route in demo_routes:
    app.routes.append(route)

# Add Changeling middleware (must be after route mounting)
app.add_middleware(Changeling, orrery=True)  # type: ignore[arg-type]
