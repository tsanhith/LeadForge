"""Job creation: parse + validate an upload into a Job with normalized Lead records."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.excel import parse_file
from app.ingest.validator import validate_rows
from app.models import Job, Lead

_LEAD_FIELDS = (
    "name", "position", "company", "website", "linkedin",
    "industry", "email", "phone", "description",
)


async def _next_job_id(session: AsyncSession) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    count = (
        await session.execute(
            select(func.count()).select_from(Job).where(Job.id.like(f"{today}-%"))
        )
    ).scalar_one()
    return f"{today}-{count + 1:03d}"


async def create_job(session: AsyncSession, *, file_path: str, filename: str) -> Job:
    """Parse the file, validate rows, persist a Job and its valid Leads.

    Invalid rows (no identity / duplicates) are counted but not queued for processing.
    """
    rows = parse_file(file_path)
    validated = validate_rows(rows)

    job_id = await _next_job_id(session)
    job = Job(id=job_id, source_filename=filename, status="processing")

    valid_count = 0
    invalid_count = 0
    for v in validated:
        if not v.valid:
            invalid_count += 1
            continue
        valid_count += 1
        lead = Lead(
            job_id=job_id,
            validation_flags=v.flags,
            status="pending",
            **{f: v.data.get(f) for f in _LEAD_FIELDS},
        )
        job.leads.append(lead)

    job.total = valid_count
    job.invalid = invalid_count
    session.add(job)
    await session.commit()
    return job
