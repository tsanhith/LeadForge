"""In-process background worker.

A single asyncio task drains a queue of job ids. For each job, its leads are processed with
bounded concurrency (one DB session per lead, since AsyncSession isn't concurrency-safe).
Job counts and status are updated as leads finish. No external broker needed for the MVP.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import SessionLocal
from app.models import Job, Lead, User
from app.pipeline.orchestrator import process_lead

logger = logging.getLogger("leadforge.worker")

_queue: asyncio.Queue[str] = asyncio.Queue()
_task: asyncio.Task | None = None


def enqueue_job(job_id: str) -> None:
    _queue.put_nowait(job_id)


def start_worker() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_run(), name="leadforge-worker")
        logger.info("worker started")


async def _run() -> None:
    while True:
        job_id = await _queue.get()
        try:
            await _process_job(job_id)
        except Exception:  # noqa: BLE001
            logger.exception("job %s crashed", job_id)
        finally:
            _queue.task_done()


async def _process_job(job_id: str) -> None:
    settings = get_settings()
    sem = asyncio.Semaphore(settings.pipeline_concurrency)

    async with SessionLocal() as session:
        lead_ids = (
            await session.execute(
                select(Lead.id).where(Lead.job_id == job_id, Lead.status == "pending")
            )
        ).scalars().all()
        company_profile = await _job_company_profile(session, job_id)

    logger.info("job %s: processing %d leads", job_id, len(lead_ids))

    async def worker(lead_id: int) -> None:
        async with sem:
            async with SessionLocal() as session:
                lead = await session.get(
                    Lead, lead_id, options=[selectinload(Lead.outreach)]
                )
                if lead is None:
                    return
                await process_lead(session, lead, company_profile)
            await _bump_counts(job_id)

    await asyncio.gather(*(worker(lid) for lid in lead_ids))
    await _finalize_job(job_id)


async def _job_company_profile(session, job_id: str) -> dict | None:
    """The company profile to pitch for this job: its uploader's. None -> built-in default."""
    job = await session.get(Job, job_id)
    if job is None or job.user_id is None:
        return None
    user = await session.get(User, job.user_id)
    return user.company_profile if user else None


async def _bump_counts(job_id: str) -> None:
    """Recompute job progress counters from its leads."""
    async with SessionLocal() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        leads = (
            await session.execute(
                select(Lead)
                .where(Lead.job_id == job_id)
                .options(selectinload(Lead.outreach))
            )
        ).scalars().all()
        threshold = get_settings().quality_threshold
        processed = high = needs = 0
        for lead in leads:
            if lead.status in ("done", "failed"):
                processed += 1
            score = lead.outreach.quality_score if lead.outreach else None
            if lead.status == "done" and score is not None:
                if score >= threshold:
                    high += 1
                else:
                    needs += 1
            elif lead.status == "failed":
                needs += 1
        job.processed = processed
        job.high_quality = high
        job.needs_review = needs
        await session.commit()


async def _finalize_job(job_id: str) -> None:
    async with SessionLocal() as session:
        job = await session.get(Job, job_id)
        if job:
            job.status = "done"
            await session.commit()
            logger.info("job %s finished", job_id)
