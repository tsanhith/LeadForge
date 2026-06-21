"""Redis-backed durable queue backend (arq).

Optional — only used when ``QUEUE_BACKEND=arq``. Requires ``pip install arq`` and a running
Redis. Run a worker (separate process, scales horizontally) with:

    arq app.pipeline.arq_worker.WorkerSettings

The task simply reuses :func:`app.pipeline.worker._process_job`, so the same per-job logic
runs whether the queue is in-process or Redis-backed.

NOTE: this backend has not been exercised in the build environment (no Redis available); the
in-process backend is the tested default.
"""
from __future__ import annotations

import logging

from arq import create_pool
from arq.connections import RedisSettings

from app.config import get_settings
from app.db import init_db
from app.pipeline.worker import _process_job

logger = logging.getLogger("leadforge.arq")


def _redis_settings() -> "RedisSettings":
    return RedisSettings.from_dsn(get_settings().redis_url)


async def process_job_task(ctx: dict, job_id: str) -> None:
    """arq task: run the full pipeline for one job's leads."""
    logger.info("arq processing job %s", job_id)
    await _process_job(job_id)


async def enqueue_job_arq(job_id: str) -> None:
    pool = await create_pool(_redis_settings())
    try:
        await pool.enqueue_job("process_job_task", job_id)
    finally:
        await pool.close()


async def _on_startup(ctx: dict) -> None:
    await init_db()


class WorkerSettings:
    """Entry point for ``arq app.pipeline.arq_worker.WorkerSettings``."""

    functions = [process_job_task]
    on_startup = _on_startup
    redis_settings = _redis_settings()
    max_jobs = 4
