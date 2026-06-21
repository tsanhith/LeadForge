"""Send orchestration: guard, deliver, record.

The web layer calls :func:`send_email_for_lead` / :func:`send_whatsapp_for_lead`. Each one:

1. runs the guards (reviewed? deliverable? not suppressed? consented?),
2. calls the channel,
3. writes the outcome back onto the lead's :class:`Outreach` row.

Guards return a human-readable reason on refusal; nothing is sent and the row is marked
``suppressed``/``failed`` accordingly so the UI can explain why.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import email as email_channel
from app.channels import suppression
from app.channels import whatsapp as whatsapp_channel
from app.config import get_settings
from app.models import Lead

logger = logging.getLogger("leadforge.send")

# Outreach must be human-reviewed before it can leave the building.
_SENDABLE_REVIEW_STATES = {"approved", "edited"}
# Source-export deliverability flags that should block an email send.
_BLOCKING_EMAIL_FLAGS = {"invalid_email", "missing_email", "unverified_email"}


@dataclass
class SendOutcome:
    ok: bool
    status: str          # the new send_status written to the row
    message: str         # human-readable result for the UI / logs


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def send_email_for_lead(session: AsyncSession, lead: Lead) -> SendOutcome:
    o = lead.outreach
    if o is None:
        return SendOutcome(False, "draft", "No outreach generated yet.")
    if o.send_status == "sent":
        return SendOutcome(True, "sent", "Already sent.")
    if o.review_status not in _SENDABLE_REVIEW_STATES:
        return SendOutcome(False, o.send_status, "Approve the draft before sending.")
    if not lead.email:
        return SendOutcome(False, "failed", "Lead has no email address.")

    blocking = _BLOCKING_EMAIL_FLAGS.intersection(lead.validation_flags or [])
    if blocking:
        o.send_status = "failed"
        o.send_error = f"blocked: {', '.join(sorted(blocking))}"
        await session.commit()
        return SendOutcome(False, "failed", f"Email blocked ({', '.join(sorted(blocking))}).")

    if await suppression.is_suppressed(session, lead.email):
        o.send_status = "suppressed"
        o.send_error = "recipient unsubscribed / on suppression list"
        await session.commit()
        return SendOutcome(False, "suppressed", "Recipient is on the do-not-contact list.")

    result = await email_channel.send_email(
        to=lead.email, subject=o.email_subject or "", body=o.email_body or ""
    )
    if result.ok:
        o.send_status = "sent"
        o.sent_at = _utcnow()
        o.provider_message_id = result.message_id
        o.send_error = None
        await session.commit()
        logger.info("email sent lead=%s via=%s id=%s", lead.id, result.provider, result.message_id)
        return SendOutcome(True, "sent", f"Sent via {result.provider}.")

    o.send_status = "failed"
    o.send_error = result.error
    await session.commit()
    return SendOutcome(False, "failed", f"Send failed: {result.error}")


async def send_whatsapp_for_lead(session: AsyncSession, lead: Lead) -> SendOutcome:
    s = get_settings()
    o = lead.outreach
    if o is None:
        return SendOutcome(False, "draft", "No outreach generated yet.")
    if o.wa_send_status == "sent":
        return SendOutcome(True, "sent", "Already sent.")
    if o.review_status not in _SENDABLE_REVIEW_STATES:
        return SendOutcome(False, o.wa_send_status, "Approve the draft before sending.")
    if not lead.phone:
        return SendOutcome(False, "failed", "Lead has no phone number.")
    if s.require_opt_in_for_whatsapp and not lead.opt_in:
        return SendOutcome(
            False, o.wa_send_status,
            "WhatsApp requires opt-in consent (Meta policy). Mark the lead opted-in first.",
        )

    result = await whatsapp_channel.send_whatsapp(to=lead.phone, body=o.whatsapp_body or "")
    if result.ok:
        o.wa_send_status = "sent"
        o.wa_sent_at = _utcnow()
        o.wa_provider_message_id = result.message_id
        o.wa_send_error = None
        await session.commit()
        logger.info("whatsapp sent lead=%s via=%s id=%s", lead.id, result.provider, result.message_id)
        return SendOutcome(True, "sent", f"Sent via {result.provider}.")

    o.wa_send_status = "failed"
    o.wa_send_error = result.error
    await session.commit()
    return SendOutcome(False, "failed", f"Send failed: {result.error}")
