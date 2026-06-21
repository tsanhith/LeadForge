"""Follow-up sequence engine.

A *sequence* is the plan that runs **after** the initial outreach: ordered steps, each a
channel + a delay + how to write the copy. When a lead's first message is sent it gets an
**enrollment**; the scheduler (``app/sequence_worker.py``) calls :func:`process_due_enrollments`
on a tick, which fires any step whose ``next_run_at`` has passed.

Stop conditions, checked before every step:
  * the lead **replied** (either channel)  → stop (the whole point of the sequence is met);
  * the lead is **suppressed/unsubscribed** → stop;
  * a step's channel is undeliverable (no address / no consent / bad email) → skip that step.

Reuses the channel senders directly, so the email unsubscribe footer and WhatsApp opt-in
rules still apply to every follow-up.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.channels import email as email_channel
from app.channels import suppression
from app.channels import whatsapp as whatsapp_channel
from app.config import get_settings
from app.models import Enrollment, Lead, Sequence, SequenceStep

logger = logging.getLogger("leadforge.sequences")

# Same deliverability flags the send service blocks on (kept local to avoid an import cycle).
_BLOCKING_EMAIL_FLAGS = {"invalid_email", "missing_email", "unverified_email"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ templates
class _SafeDict(dict):
    def __missing__(self, key):  # leave unknown placeholders blank rather than crashing
        return ""


def render_template(text: str | None, lead: Lead) -> str:
    if not text:
        return ""
    first = (lead.name or "there").split()[0] if lead.name else "there"
    return text.format_map(_SafeDict(
        first_name=first,
        name=lead.name or "there",
        company=lead.company or "your team",
    ))


# ------------------------------------------------------------------ enrollment
async def default_sequence(session: AsyncSession) -> Sequence | None:
    for clause in (Sequence.is_default == 1, Sequence.active == 1):
        seq = (
            await session.execute(
                select(Sequence).where(clause).options(selectinload(Sequence.steps)).limit(1)
            )
        ).scalars().first()
        if seq:
            return seq
    return None


async def get_enrollment(session: AsyncSession, lead_id: int) -> Enrollment | None:
    return (
        await session.execute(select(Enrollment).where(Enrollment.lead_id == lead_id))
    ).scalar_one_or_none()


async def enroll_lead(session: AsyncSession, lead: Lead) -> Enrollment | None:
    """Enroll a lead into the default sequence after its initial message is sent."""
    s = get_settings()
    if not s.sequences_enabled:
        return None
    if await get_enrollment(session, lead.id) is not None:
        return None  # already enrolled
    seq = await default_sequence(session)
    if seq is None or not seq.steps:
        return None
    enr = Enrollment(
        lead_id=lead.id,
        sequence_id=seq.id,
        status="active",
        current_step=0,
        next_run_at=_utcnow() + timedelta(days=seq.steps[0].delay_days),
    )
    session.add(enr)
    await session.commit()
    logger.info("enrolled lead %s into sequence '%s'", lead.id, seq.name)
    return enr


async def stop_enrollment(session: AsyncSession, lead_id: int, reason: str) -> bool:
    """Stop a lead's active enrollment (used on reply/bounce and from the UI)."""
    enr = await get_enrollment(session, lead_id)
    if enr is None or enr.status != "active":
        return False
    enr.status = "stopped"
    enr.stop_reason = reason
    enr.next_run_at = None
    await session.commit()
    return True


async def restart_enrollment(session: AsyncSession, lead_id: int) -> bool:
    """Re-activate a stopped/completed enrollment, resuming promptly."""
    enr = await get_enrollment(session, lead_id)
    if enr is None:
        return False
    seq = await session.get(Sequence, enr.sequence_id, options=[selectinload(Sequence.steps)])
    if seq is None or not seq.steps:
        return False
    if enr.current_step >= len(seq.steps):
        enr.current_step = 0  # completed -> start over
    enr.status = "active"
    enr.stop_reason = None
    enr.next_run_at = _utcnow()
    await session.commit()
    return True


def _complete(enr: Enrollment) -> None:
    enr.status = "completed"
    enr.next_run_at = None


def _stop(enr: Enrollment, reason: str) -> None:
    enr.status = "stopped"
    enr.stop_reason = reason
    enr.next_run_at = None


# ------------------------------------------------------------------ stepping
async def _compose(step: SequenceStep, lead: Lead, follow_up_number: int) -> tuple[str | None, str]:
    """Produce (subject, body) for a step — generated if asked, else the template."""
    subject = render_template(step.subject_template, lead) if step.subject_template else None
    body = render_template(step.body_template, lead)

    if step.generate and get_settings().sequences_enabled:
        try:
            from app.agents.followup import generate_followup  # lazy: avoid LLM import cost

            o = lead.outreach
            angle = (lead.opportunity or {}).get("outreach_angle") if lead.opportunity else None
            fc = await generate_followup(
                channel=step.channel,
                follow_up_number=follow_up_number,
                name=lead.name,
                company=lead.company,
                position=lead.position,
                original_subject=o.email_subject if o else None,
                original_body=(o.email_body or o.whatsapp_body) if o else None,
                outreach_angle=angle,
            )
            if fc.message.strip():
                body = fc.message.strip()
                if step.channel == "email" and fc.subject.strip():
                    subject = fc.subject.strip()
        except Exception:  # noqa: BLE001 — generation is best-effort; template is the fallback
            logger.warning("follow-up generation failed for lead %s; using template", lead.id)
    return subject, body


async def _deliver_step(
    session: AsyncSession, lead: Lead, step: SequenceStep, enr: Enrollment, now: datetime
) -> bool:
    """Send one step. Returns True if a message actually went out."""
    s = get_settings()
    o = lead.outreach

    if step.channel == "email":
        if not lead.email or _BLOCKING_EMAIL_FLAGS.intersection(lead.validation_flags or []):
            return False
        subject, body = await _compose(step, lead, enr.current_step + 1)
        result = await email_channel.send_email(lead.email, subject or "", body)
        if o:
            if result.ok:
                o.send_status = "sent"
                o.sent_at = now
                o.provider_message_id = result.message_id
                o.send_error = None
            else:
                o.send_status = "failed"
                o.send_error = result.error
        _snapshot(enr, "email", subject, body, now)
        return result.ok

    # whatsapp
    if not lead.phone or (s.require_opt_in_for_whatsapp and not lead.opt_in):
        return False
    _, body = await _compose(step, lead, enr.current_step + 1)
    result = await whatsapp_channel.send_whatsapp(lead.phone, body)
    if o:
        if result.ok:
            o.wa_send_status = "sent"
            o.wa_sent_at = now
            o.wa_provider_message_id = result.message_id
            o.wa_send_error = None
        else:
            o.wa_send_status = "failed"
            o.wa_send_error = result.error
    _snapshot(enr, "whatsapp", None, body, now)
    return result.ok


def _snapshot(enr: Enrollment, channel: str, subject: str | None, body: str, now: datetime) -> None:
    enr.last_sent_at = now
    enr.last_channel = channel
    enr.last_subject = subject
    enr.last_body = body


async def process_enrollment_step(
    session: AsyncSession, enr: Enrollment, now: datetime | None = None
) -> str:
    """Advance one enrollment by (at most) one step. Returns an outcome label."""
    now = now or _utcnow()
    lead = await session.get(Lead, enr.lead_id, options=[selectinload(Lead.outreach)])
    seq = await session.get(Sequence, enr.sequence_id, options=[selectinload(Sequence.steps)])
    if lead is None or seq is None:
        _stop(enr, "missing_data")
        await session.commit()
        return "stopped"

    steps = list(seq.steps)
    if enr.current_step >= len(steps):
        _complete(enr)
        await session.commit()
        return "completed"

    # Global stop conditions.
    o = lead.outreach
    if o and (o.send_status == "replied" or o.wa_send_status == "replied"):
        _stop(enr, "replied")
        await session.commit()
        return "stopped"
    if await suppression.is_suppressed(session, lead.email):
        _stop(enr, "unsubscribed")
        await session.commit()
        return "stopped"

    step = steps[enr.current_step]
    sent = await _deliver_step(session, lead, step, enr, now)

    enr.current_step += 1
    if enr.current_step >= len(steps):
        _complete(enr)
    else:
        enr.next_run_at = now + timedelta(days=steps[enr.current_step].delay_days)
    await session.commit()
    logger.info(
        "lead %s sequence step %d -> %s", lead.id, step.step_order, "sent" if sent else "skipped"
    )
    return "sent" if sent else "skipped"


async def process_due_enrollments(session: AsyncSession, now: datetime | None = None) -> int:
    """Fire every active enrollment whose next step is due. Returns how many were processed."""
    now = now or _utcnow()
    due = (
        await session.execute(
            select(Enrollment).where(
                Enrollment.status == "active",
                Enrollment.next_run_at.isnot(None),
                Enrollment.next_run_at <= now,
            )
        )
    ).scalars().all()
    processed = 0
    for enr in due:
        try:
            await process_enrollment_step(session, enr, now)
            processed += 1
        except Exception:  # noqa: BLE001 — one bad enrollment shouldn't stall the rest
            await session.rollback()
            logger.exception("enrollment %s step failed", enr.id)
    return processed
