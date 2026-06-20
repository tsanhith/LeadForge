import pytest

from app.llm import gateway
from app.llm.gateway import _parse_json
from app.llm.providers.base import ChatResult, ProviderError


def test_parse_json_plain():
    assert _parse_json('{"a": 1}') == {"a": 1}


def test_parse_json_fenced_with_prose():
    text = 'Sure!\n```json\n{"a": 1, "b": [2,3]}\n```\nHope that helps.'
    assert _parse_json(text) == {"a": 1, "b": [2, 3]}


def test_parse_json_embedded_braces():
    assert _parse_json('prefix {"x": "y"} suffix') == {"x": "y"}


class FakeProvider:
    def __init__(self, name, *, configured=True, fail=False):
        self.name = name
        self.configured = configured
        self.fail = fail
        self.calls = 0

    async def chat(self, messages, model, **kwargs):
        self.calls += 1
        if self.fail:
            raise ProviderError(f"{self.name} boom")
        return ChatResult(text='{"ok": true}', model=model, provider=self.name)


@pytest.mark.asyncio
async def test_complete_uses_primary(monkeypatch):
    primary = FakeProvider("openrouter")
    secondary = FakeProvider("nvidia_nim")
    monkeypatch.setattr(gateway, "get_providers", lambda: {"openrouter": primary, "nvidia_nim": secondary})

    resp = await gateway.complete("email", [{"role": "user", "content": "hi"}])
    assert resp.provider == "openrouter"
    assert resp.json() == {"ok": True}
    assert primary.calls == 1
    assert secondary.calls == 0


@pytest.mark.asyncio
async def test_complete_falls_back(monkeypatch):
    primary = FakeProvider("openrouter", fail=True)
    secondary = FakeProvider("nvidia_nim")
    monkeypatch.setattr(gateway, "get_providers", lambda: {"openrouter": primary, "nvidia_nim": secondary})

    # 'email' routes to openrouter; it fails -> should fall back to nvidia_nim.
    resp = await gateway.complete("email", [{"role": "user", "content": "hi"}])
    assert resp.provider == "nvidia_nim"
    assert secondary.calls == 1


@pytest.mark.asyncio
async def test_complete_all_fail_raises(monkeypatch):
    primary = FakeProvider("openrouter", fail=True)
    secondary = FakeProvider("nvidia_nim", fail=True)
    monkeypatch.setattr(gateway, "get_providers", lambda: {"openrouter": primary, "nvidia_nim": secondary})

    with pytest.raises(ProviderError):
        await gateway.complete("email", [{"role": "user", "content": "hi"}])
