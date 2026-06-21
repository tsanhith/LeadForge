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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.channels import email as email_channel
from app.channels import suppression
from app.channels import whatsapp as whatsapp_channel
from app.channels.whatsapp import normalize_msisdn
from app.config import get_settings
from app.models import Lead, Outreach, Suppression

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


# --------------------------------------------------------------------------- bulk actions
async def _job_leads(session: AsyncSession, job_id: str) -> list[Lead]:
    return list(
        (
            await session.execute(
                select(Lead)
                .where(Lead.job_id == job_id)
                .options(selectinload(Lead.outreach))
            )
        ).scalars().all()
    )


async def bulk_approve(session: AsyncSession, job_id: str, min_score: float) -> int:
    """Approve every still-pending draft in the job scoring at/above ``min_score``."""
    count = 0
    for lead in await _job_leads(session, job_id):
        o = lead.outreach
        if o and o.review_status == "pending" and (o.quality_score or 0) >= min_score:
            o.review_status = "approved"
            count += 1
    if count:
        await session.commit()
    return count


async def bulk_queue(session: AsyncSession, job_id: str, channel: str) -> dict:
    """Queue every eligible, reviewed lead in the job for throttled sending.

    Returns ``{"queued": n, "skipped": m}``. Ineligible leads (unreviewed, already
    sent/queued, missing destination, suppressed, or — for WhatsApp — not opted in) are
    skipped here so the queue only holds messages that should actually go out.
    """
    s = get_settings()
    leads = await _job_leads(session, job_id)

    suppressed: set[str] = set()
    if channel == "email":
        emails = [(l.email or "").lower() for l in leads if l.email]
        if emails:
            suppressed = {
                row[0]
                for row in (
                    await session.execute(
                        select(Suppression.email).where(Suppression.email.in_(emails))
                    )
                ).all()
            }

    queued = skipped = 0
    for lead in leads:
        o = lead.outreach
        if not o or o.review_status not in _SENDABLE_REVIEW_STATES:
            skipped += 1
            continue
        if channel == "email":
            blocked = _BLOCKING_EMAIL_FLAGS.intersection(lead.validation_flags or [])
            if (
                o.send_status in ("sent", "queued")
                or not lead.email
                or blocked
                or (lead.email or "").lower() in suppressed
            ):
                skipped += 1
                continue
            o.send_status = "queued"
            o.send_error = None
            queued += 1
        else:  # whatsapp
            if (
                o.wa_send_status in ("sent", "queued")
                or not lead.phone
                or (s.require_opt_in_for_whatsapp and not lead.opt_in)
            ):
                skipped += 1
                continue
            o.wa_send_status = "queued"
            o.wa_send_error = None
            queued += 1
    if queued:
        await session.commit()
    return {"queued": queued, "skipped": skipped}


# ----------------------------------------------------------------- inbound delivery events
# Map a provider's event name onto how we record it.
_BOUNCE_EVENTS = {"bounce", "bounced", "hard_bounce", "hardbounce", "dropped", "failed"}
_COMPLAINT_EVENTS = {"complaint", "complained", "spam", "spamreport"}
_REPLY_EVENTS = {"reply", "replied", "inbound"}


async def record_email_event(session: AsyncSession, email: str, event: str) -> int:
    """Apply a bounce/complaint/reply from an email webhook to matching outreach.

    Hard bounces and complaints also add the address to the suppression list so it's never
    contacted again — the single most important thing for protecting domain reputation.
    """
    norm = (email or "").strip().lower()
    ev = (event or "").strip().lower()
    if not norm:
        return 0

    rows = (
        await session.execute(
            select(Outreach).join(Lead).where(Lead.email.ilike(norm))
        )
    ).scalars().all()

    if ev in _BOUNCE_EVENTS or ev in _COMPLAINT_EVENTS:
        reason = "complaint" if ev in _COMPLAINT_EVENTS else "bounce"
        for o in rows:
            o.send_status = "bounced"
            o.send_error = f"{reason} reported via webhook"
        await suppression.add_suppression(session, norm, reason=reason)
    elif ev in _REPLY_EVENTS:
        for o in rows:
            o.send_status = "replied"
    else:
        return 0
    await session.commit()
    return len(rows)


async def record_whatsapp_event(session: AsyncSession, recipient: str, event: str) -> int:
    """Apply a delivery/read/failed/reply event from a WhatsApp webhook by phone number."""
    digits = normalize_msisdn(recipient)
    ev = (event or "").strip().lower()
    if not digits:
        return 0

    # Phone numbers are stored in varied formats, so normalize and match in Python rather
    # than in SQL.
    rows = [
        o
        for o in (
            await session.execute(
                select(Outreach).join(Lead).options(selectinload(Outreach.lead))
            )
        ).scalars().all()
        if o.lead and normalize_msisdn(o.lead.phone or "") == digits
    ]

    if not rows:
        return 0
    if ev in _BOUNCE_EVENTS:
        for o in rows:
            o.wa_send_status = "bounced"
            o.wa_send_error = "delivery failed (webhook)"
    elif ev in _REPLY_EVENTS:
        for o in rows:
            o.wa_send_status = "replied"
    else:
        return 0
    await session.commit()
    return len(rows)
