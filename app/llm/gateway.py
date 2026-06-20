"""The LLM Gateway — the single entry point for every model call in the app.

Agents call ``complete(task=..., messages=...)``. The gateway:
  * resolves the task to a (provider, model) via routes,
  * retries transient failures,
  * falls back to other configured providers (in config order) if the primary fails,
  * logs model/latency/token usage,
  * optionally parses + repairs JSON output for structured agents.

Nothing outside this module imports a provider class. Swapping models is a config edit.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass

from app.config import get_settings
from app.llm import routes
from app.llm.providers.base import ChatResult, ProviderError
from app.llm.providers.openai_compatible import OpenAICompatibleProvider

logger = logging.getLogger("leadforge.llm")


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    task: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int

    def json(self) -> dict:
        """Parse the response text as JSON, tolerating code fences / surrounding prose."""
        return _parse_json(self.text)


# --- provider registry (built once from settings) --------------------------------------
_providers: dict[str, OpenAICompatibleProvider] | None = None


def _build_providers() -> dict[str, OpenAICompatibleProvider]:
    s = get_settings()
    return {
        "openrouter": OpenAICompatibleProvider(
            "openrouter",
            s.openrouter_base_url,
            s.openrouter_api_key,
            timeout=s.request_timeout,
            # OpenRouter likes these for attribution; harmless if unused.
            extra_headers={
                "HTTP-Referer": "https://github.com/tsanhith/LeadForge",
                "X-Title": "LeadForge",
            },
        ),
        "nvidia_nim": OpenAICompatibleProvider(
            "nvidia_nim",
            s.nvidia_nim_base_url,
            s.nvidia_nim_api_key,
            timeout=s.request_timeout,
        ),
    }


def get_providers() -> dict[str, OpenAICompatibleProvider]:
    global _providers
    if _providers is None:
        _providers = _build_providers()
    return _providers


def reset_providers() -> None:
    """Test hook: force providers to be rebuilt from current settings."""
    global _providers
    _providers = None


def _provider_order(primary: str) -> list[str]:
    """Primary first, then the rest of the configured fallback order (deduped)."""
    order = [primary] + [p for p in get_settings().fallback_order if p != primary]
    seen: set[str] = set()
    result: list[str] = []
    for p in order:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


async def complete(
    task: str,
    messages: list[dict],
    *,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    json_mode: bool = False,
) -> LLMResponse:
    settings = get_settings()
    primary, model = routes.resolve(task)
    providers = get_providers()

    last_error: Exception | None = None
    for provider_name in _provider_order(primary):
        provider = providers.get(provider_name)
        if provider is None or not provider.configured:
            continue
        # Use the primary's model only on the primary provider; fall back providers use
        # their own routed default model so we never send an unknown model id.
        use_model = model if provider_name == primary else _fallback_model(provider_name)

        for attempt in range(settings.max_retries + 1):
            start = time.perf_counter()
            try:
                result: ChatResult = await provider.chat(
                    messages,
                    use_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )
                latency_ms = int((time.perf_counter() - start) * 1000)
                logger.info(
                    "llm task=%s provider=%s model=%s latency=%dms tokens=%d/%d",
                    task, provider_name, use_model, latency_ms,
                    result.prompt_tokens, result.completion_tokens,
                )
                return LLMResponse(
                    text=result.text,
                    provider=provider_name,
                    model=use_model,
                    task=task,
                    latency_ms=latency_ms,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                )
            except ProviderError as exc:
                last_error = exc
                logger.warning(
                    "llm task=%s provider=%s attempt=%d failed: %s",
                    task, provider_name, attempt + 1, exc,
                )
                if attempt < settings.max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
        # exhausted retries on this provider -> try next provider

    raise ProviderError(
        f"all providers failed for task '{task}': {last_error}"
    )


def _fallback_model(provider_name: str) -> str:
    """Pick a reasonable model for a fallback provider from its own routes."""
    from app.config import MODEL_ROUTES

    for _task, (prov, model) in MODEL_ROUTES.items():
        if prov == provider_name:
            return model
    # last resort
    return "meta/llama-3.1-8b-instruct"


# --- JSON parsing helpers --------------------------------------------------------------
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _parse_json(text: str) -> dict:
    text = text.strip()
    # 1) direct
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2) inside a ``` fence
    m = _FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 3) first {...} balanced-ish slice
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"could not parse JSON from LLM output: {text[:300]}")
