"""Provider abstraction.

A provider only knows how to turn (messages, model) into text. It has no idea which agent
or task is calling it. The gateway is responsible for choosing the provider + model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ChatResult:
    text: str
    model: str
    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: dict = field(default_factory=dict)


class ProviderError(RuntimeError):
    """Raised when a provider call fails (network, auth, rate limit, bad status)."""


class Provider(Protocol):
    name: str

    async def chat(
        self,
        messages: list[dict],
        model: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> ChatResult: ...
