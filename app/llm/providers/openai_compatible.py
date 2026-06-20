"""A single OpenAI-compatible chat client.

Both OpenRouter and NVIDIA NIM expose the same ``POST /chat/completions`` shape, so they are
just two instances of this class differing by base URL + API key.
"""
from __future__ import annotations

import httpx

from .base import ChatResult, ProviderError


class OpenAICompatibleProvider:
    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 60.0,
        extra_headers: dict | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.extra_headers = extra_headers or {}

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def chat(
        self,
        messages: list[dict],
        model: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> ChatResult:
        if not self.configured:
            raise ProviderError(f"provider '{self.name}' has no API key configured")

        payload: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=headers
                )
        except httpx.HTTPError as exc:  # network/timeout
            raise ProviderError(f"{self.name}: request failed: {exc}") from exc

        if resp.status_code >= 400:
            raise ProviderError(
                f"{self.name}: HTTP {resp.status_code}: {resp.text[:500]}"
            )

        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"{self.name}: unexpected response shape: {data}") from exc

        usage = data.get("usage") or {}
        return ChatResult(
            text=text,
            model=model,
            provider=self.name,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )
