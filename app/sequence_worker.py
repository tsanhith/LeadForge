"""Background scheduler for follow-up sequences.

Wakes on a slow tick (sequence delays are measured in days, so there's no need to poll
often), and within the configured send window releases any due follow-up steps. Like the
send worker, all state lives in the database, so a restart simply resumes.
"""
from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.db import SessionLocal
from app.send_worker import in_send_window
from app.sequences import process_due_enrollments

logger = logging.getLogger("leadforge.sequence_worker")

_TICK_SECONDS = 60
_task: asyncio.Task | None = None


def start_sequence_worker() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_run(), name="leadforge-sequence-worker")
        logger.info("sequence worker started")


async def _run() -> None:
    while True:
        try:
            if get_settings().sequences_enabled and in_send_window():
                async with SessionLocal() as session:
                    n = await process_due_enrollments(session)
                if n:
                    logger.info("processed %d due follow-up(s)", n)
        except Exception:  # noqa: BLE001 — never let the loop die
            logger.exception("sequence worker tick failed")
        await asyncio.sleep(_TICK_SECONDS)
