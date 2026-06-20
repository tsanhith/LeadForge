"""Task -> (provider, model) resolution. Thin wrapper over config so callers import here."""
from __future__ import annotations

from app.config import DEFAULT_ROUTE, MODEL_ROUTES


def resolve(task: str) -> tuple[str, str]:
    """Return (provider_name, model) for a pipeline task."""
    return MODEL_ROUTES.get(task, DEFAULT_ROUTE)
