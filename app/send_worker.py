"""Throttled background sender.

Bulk sends aren't fired all at once — they're *queued* (``send_status='queued'`` /
``wa_send_status='queued'`` on the Outreach row) and this worker releases them one at a time
at ``send_rate_per_hour``, within the configured send window, with random jitter so the
cadence looks human. Because the queue lives in the database, a restart simply resumes where
it left off (no in-memory state to lose) — unlike a cold blast, which gets a young sending
domain throttled or blocked.

``process_next_send`` does exactly one unit of work and is independently testable; ``_run``
just calls it on a paced loop.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import SessionLocal
from app.models import Lead, Outreach
from app.send_service import send_email_for_lead, send_whatsapp_for_lead

logger = logging.getLogger("leadforge.send_worker")

_task: asyncio.Task | None = None


def start_send_worker() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_run(), name="leadforge-send-worker")
        logger.info("send worker started")


def in_send_window(now: datetime | None = None) -> bool:
    """True if the local hour falls inside [start, end) (wrapping past midnight allowed)."""
    s = get_settings()
    start, end = s.send_window_start_hour, s.send_window_end_hour
    hour = (now or datetime.now()).hour
    if start == end:
        return True  # zero-width window is treated as "always on"
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # window wraps midnight


def _next_gap() -> float:
    s = get_settings()
    base = s.send_interval_seconds
    jitter = max(0.0, min(s.send_jitter, 0.95))
    return max(1.0, base * (1.0 + random.uniform(-jitter, jitter)))


async def process_next_send(session) -> tuple[str, int] | None:
    """Release the single oldest queued message (email first, then WhatsApp).

    Returns ``(channel, lead_id)`` if something was sent, else ``None``.
    """
    # Oldest queued email.
    lead = (
        await session.execute(
            select(Lead)
            .join(Outreach)
            .where(Outreach.send_status == "queued")
            .options(selectinload(Lead.outreach))
            .order_by(Outreach.updated_at)
            .limit(1)
        )
    ).scalars().first()
    if lead is not None:
        await send_email_for_lead(session, lead)
        return ("email", lead.id)

    # Oldest queued WhatsApp.
    lead = (
        await session.execute(
            select(Lead)
            .join(Outreach)
            .where(Outreach.wa_send_status == "queued")
            .options(selectinload(Lead.outreach))
            .order_by(Outreach.updated_at)
            .limit(1)
        )
    ).scalars().first()
    if lead is not None:
        await send_whatsapp_for_lead(session, lead)
        return ("whatsapp", lead.id)

    return None


async def _run() -> None:
    while True:
        try:
            if not in_send_window():
                await asyncio.sleep(60)
                continue
            async with SessionLocal() as session:
                sent = await process_next_send(session)
            if sent:
                logger.info("released %s for lead %s", *sent)
                await asyncio.sleep(_next_gap())
            else:
                await asyncio.sleep(5)  # queue empty — idle poll
        except Exception:  # noqa: BLE001 — never let the loop die
            logger.exception("send worker tick failed")
            await asyncio.sleep(5)
