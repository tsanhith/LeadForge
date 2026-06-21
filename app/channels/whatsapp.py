"""WhatsApp channel — Meta WhatsApp Business Cloud API (or a console mock).

``send_whatsapp(to, body)`` dispatches to the configured provider:

* ``console`` — logs the message and reports success (default; runs before a WhatsApp
  Business account exists);
* ``meta``    — Meta's Graph API ``/{phone_number_id}/messages`` endpoint.

Meta requires a **pre-approved template** for the first message to a contact; free-form text
is only allowed inside the 24-hour customer-service window. So when ``whatsapp_template_name``
is configured we send a template (passing the generated copy as body parameter ``{{1}}``),
otherwise we send plain text and let Meta enforce the window.
"""
from __future__ import annotations

import logging
import re
import uuid

import httpx

from app.channels.base import SendResult
from app.config import Settings, get_settings

logger = logging.getLogger("leadforge.channels.whatsapp")


def normalize_msisdn(phone: str) -> str:
    """Meta expects digits only, in E.164 without the leading '+'."""
    return re.sub(r"\D", "", phone or "")


async def send_whatsapp(to: str, body: str) -> SendResult:
    s = get_settings()
    if s.whatsapp_provider == "meta":
        return await _send_meta(s, to, body)
    return _send_console(to, body)


def _send_console(to: str, body: str) -> SendResult:
    logger.info("[console whatsapp] to=%s\n%s", to, body)
    return SendResult(ok=True, provider="console", message_id=f"console-{uuid.uuid4().hex}")


async def _send_meta(s: Settings, to: str, body: str) -> SendResult:
    if not (s.whatsapp_token and s.whatsapp_phone_number_id):
        return SendResult(
            ok=False, provider="meta",
            error="WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID not configured",
        )
    msisdn = normalize_msisdn(to)
    if not msisdn:
        return SendResult(ok=False, provider="meta", error="recipient has no phone number")

    url = (
        f"https://graph.facebook.com/{s.whatsapp_api_version}"
        f"/{s.whatsapp_phone_number_id}/messages"
    )
    if s.whatsapp_template_name:
        payload = {
            "messaging_product": "whatsapp",
            "to": msisdn,
            "type": "template",
            "template": {
                "name": s.whatsapp_template_name,
                "language": {"code": s.whatsapp_template_lang},
                "components": [
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": body}],
                    }
                ],
            },
        }
    else:
        payload = {
            "messaging_product": "whatsapp",
            "to": msisdn,
            "type": "text",
            "text": {"body": body},
        }

    headers = {"Authorization": f"Bearer {s.whatsapp_token}"}
    try:
        async with httpx.AsyncClient(timeout=s.request_timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            return SendResult(
                ok=False, provider="meta", error=f"HTTP {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json() or {}
        msg_id = (data.get("messages") or [{}])[0].get("id")
        return SendResult(ok=True, provider="meta", message_id=msg_id)
    except httpx.HTTPError as exc:
        return SendResult(ok=False, provider="meta", error=str(exc)[:300])
