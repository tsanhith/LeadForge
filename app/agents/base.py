"""Shared agent helper.

Each agent builds messages, asks the gateway for JSON, and validates the result into a
Pydantic schema. Agents import ONLY ``app.llm.gateway`` — never a provider — preserving the
rule that the application never knows which model runs.
"""
from __future__ import annotations

import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.llm import gateway

logger = logging.getLogger("leadforge.agents")

T = TypeVar("T", bound=BaseModel)


async def run_json_agent(
    *,
    task: str,
    system: str,
    user: str,
    schema: type[T],
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> T:
    """Call the gateway in JSON mode and validate into ``schema``.

    On parse/validation failure, returns a best-effort default instance of the schema so a
    single bad lead never crashes the whole pipeline. The raw error is logged.
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    resp = await gateway.complete(
        task, messages, temperature=temperature, max_tokens=max_tokens, json_mode=True
    )
    try:
        data = resp.json()
        return schema.model_validate(data)
    except (ValueError, ValidationError) as exc:
        logger.warning("agent task=%s could not validate output: %s", task, exc)
        return schema()
