"""Email channel — provider behind one small interface.

``send_email(to, subject, body)`` dispatches to the configured provider:

* ``console`` — logs the rendered email and reports success (the default; lets the whole
  pipeline run before a real mailbox exists);
* ``smtp``    — any SMTP relay (Google Workspace / Microsoft 365 / SES SMTP), via stdlib
  ``smtplib`` on a worker thread so we don't block the event loop;
* ``resend``  — the Resend transactional HTTP API.

A CAN-SPAM/GDPR-compliant unsubscribe footer (with a physical address and one-click link) is
appended to every message here, so no send path can forget it.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
import uuid
from email.message import EmailMessage
from email.utils import make_msgid
from urllib.parse import quote

import httpx

from app.channels.base import SendResult
from app.config import Settings, get_settings

logger = logging.getLogger("leadforge.channels.email")


def unsubscribe_url(to_email: str, settings: Settings | None = None) -> str:
    s = settings or get_settings()
    return f"{s.public_base_url.rstrip('/')}/unsubscribe?email={quote(to_email)}"


def with_unsubscribe_footer(body: str, to_email: str, settings: Settings | None = None) -> str:
    """Append the legally-required footer to an email body."""
    s = settings or get_settings()
    footer = (
        "\n\n"
        "—\n"
        f"You received this email because we believe {s.email_from_name} may be relevant "
        "to your work. If we got that wrong, we're sorry for the interruption.\n"
        f"Unsubscribe: {unsubscribe_url(to_email, s)}\n"
        f"{s.company_postal_address}"
    )
    return body.rstrip() + footer


async def send_email(to: str, subject: str, body: str) -> SendResult:
    """Send one email through the configured provider. Footer is added here."""
    s = get_settings()
    full_body = with_unsubscribe_footer(body, to, s)

    if s.email_provider == "smtp":
        return await _send_smtp(s, to, subject, full_body)
    if s.email_provider == "resend":
        return await _send_resend(s, to, subject, full_body)
    return _send_console(to, subject, full_body)


# ---------------------------------------------------------------- providers
def _send_console(to: str, subject: str, body: str) -> SendResult:
    logger.info(
        "[console email] to=%s subject=%r\n%s", to, subject, body
    )
    return SendResult(ok=True, provider="console", message_id=f"console-{uuid.uuid4().hex}")


async def _send_smtp(s: Settings, to: str, subject: str, body: str) -> SendResult:
    if not s.smtp_host:
        return SendResult(ok=False, provider="smtp", error="SMTP_HOST not configured")

    def _blocking() -> str:
        msg = EmailMessage()
        msg["From"] = f"{s.email_from_name} <{s.email_from}>"
        msg["To"] = to
        msg["Subject"] = subject
        if s.email_reply_to:
            msg["Reply-To"] = s.email_reply_to
        message_id = make_msgid()
        msg["Message-ID"] = message_id
        msg.set_content(body)
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as server:
            if s.smtp_starttls:
                server.starttls()
            if s.smtp_username:
                server.login(s.smtp_username, s.smtp_password)
            server.send_message(msg)
        return message_id

    try:
        message_id = await asyncio.to_thread(_blocking)
        return SendResult(ok=True, provider="smtp", message_id=message_id)
    except Exception as exc:  # noqa: BLE001 — surface any SMTP error to the UI
        logger.warning("smtp send to %s failed: %s", to, exc)
        return SendResult(ok=False, provider="smtp", error=str(exc)[:300])


async def _send_resend(s: Settings, to: str, subject: str, body: str) -> SendResult:
    if not s.resend_api_key:
        return SendResult(ok=False, provider="resend", error="RESEND_API_KEY not configured")
    payload = {
        "from": f"{s.email_from_name} <{s.email_from}>",
        "to": [to],
        "subject": subject,
        "text": body,
    }
    if s.email_reply_to:
        payload["reply_to"] = s.email_reply_to
    headers = {"Authorization": f"Bearer {s.resend_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=s.request_timeout) as client:
            resp = await client.post(
                "https://api.resend.com/emails", json=payload, headers=headers
            )
        if resp.status_code >= 400:
            return SendResult(
                ok=False, provider="resend", error=f"HTTP {resp.status_code}: {resp.text[:200]}"
            )
        return SendResult(
            ok=True, provider="resend", message_id=(resp.json() or {}).get("id")
        )
    except httpx.HTTPError as exc:
        return SendResult(ok=False, provider="resend", error=str(exc)[:300])
