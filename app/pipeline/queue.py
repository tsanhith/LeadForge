"""Job queue abstraction + restart recovery.

The app enqueues a job by id; *how* it runs depends on ``queue_backend``:

* ``inprocess`` (default) — the built-in asyncio worker in :mod:`app.pipeline.worker`. No
  extra infrastructure. Durability across restarts comes from :func:`recover_pending_jobs`,
  which re-enqueues any job that wasn't finished (the job/lead state lives in the DB).
* ``arq`` — a Redis-backed durable queue (:mod:`app.pipeline.arq_worker`) that also scales
  horizontally: run one or more ``arq app.pipeline.arq_worker.WorkerSettings`` processes.

Either way the source of truth is the database, so recovery is just "find unfinished work
and enqueue it again" — safe because re-processing a lead is idempotent (it overwrites its
own outreach row).
"""
from __future__ import annotations

import logging

from sqlalchemy import select, update

from app.config import get_settings
from app.db import SessionLocal
from app.models import Job, Lead
from app.pipeline import worker as inproc

logger = logging.getLogger("leadforge.queue")


async def enqueue_job(job_id: str) -> None:
    """Hand a job to the configured backend for processing."""
    if get_settings().queue_backend == "arq":
        from app.pipeline.arq_worker import enqueue_job_arq  # lazy: arq is optional

        await enqueue_job_arq(job_id)
    else:
        inproc.enqueue_job(job_id)


async def reset_and_collect(session) -> list[str]:
    """Reset mid-flight leads to pending and return the ids of unfinished jobs."""
    await session.execute(
        update(Lead).where(Lead.status == "processing").values(status="pending")
    )
    await session.commit()
    return list(
        (await session.execute(select(Job.id).where(Job.status != "done"))).scalars().all()
    )


async def recover_pending_jobs() -> int:
    """Re-enqueue jobs interrupted by a restart. Returns how many were recovered.

    Any lead left mid-flight (``status='processing'``) is reset to ``pending`` so the worker
    picks it up again; any job not marked ``done`` is re-enqueued.
    """
    async with SessionLocal() as session:
        job_ids = await reset_and_collect(session)

    for job_id in job_ids:
        await enqueue_job(job_id)
    if job_ids:
        logger.info("recovered %d unfinished job(s) after restart", len(job_ids))
    return len(job_ids)
