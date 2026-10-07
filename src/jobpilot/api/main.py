"""FastAPI application entrypoint and route definitions."""

import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, status

from jobpilot.config import get_settings


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structured console logging."""
    log_fmt = (
        '{"time":"%(asctime)s", "level":"%(levelname)s", '
        '"name":"%(name)s", "message":"%(message)s"}'
    )
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format=log_fmt,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan events."""
    settings = get_settings()
    configure_logging(settings.log_level)
    logging.info("Starting JobPilot API in %s environment", settings.app_env)
    yield
    logging.info("Shutting down JobPilot API")


app = FastAPI(
    title="JobPilot API",
    description="Inbox-aware job-search assistant API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/healthz", status_code=status.HTTP_200_OK, tags=["Health"])
async def healthz() -> dict[str, Any]:
    """Liveness probe endpoint."""
    return {
        "status": "ok",
        "service": "jobpilot-api",
        "version": "0.1.0",
    }
