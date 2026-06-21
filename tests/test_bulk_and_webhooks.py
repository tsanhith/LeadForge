"""Bulk approve/queue, throttled drain, and inbound webhook tests (in-memory DB, console)."""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.channels import suppression
from app.db import Base
from app.models import Job, Lead, Outreach
from app.send_service import (
    bulk_approve,
    bulk_queue,
    record_email_event,
    record_whatsapp_event,
)
from app.send_worker import in_send_window, process_next_send


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _make_job(session, specs: list[dict]) -> str:
    """specs: dicts with score/review/email/phone/opt_in/flags overrides."""
    job = Job(id="2026-06-21-001", source_filename="x.csv")
    session.add(job)
    await session.flush()
    for i, sp in enumerate(specs):
        lead = Lead(
            job_id=job.id,
            name=f"Lead {i}",
            email=sp.get("email", f"lead{i}@corp.com"),
            phone=sp.get("phone", "+1 555 010%d" % i),
            validation_flags=sp.get("flags", []),
            opt_in=sp.get("opt_in", 0),
        )
        session.add(lead)
        await session.flush()
        o = Outreach(
            lead_id=lead.id,
            email_subject="Hi",
            email_body="Body",
            whatsapp_body="Hey",
            quality_score=sp.get("score", 8.0),
            review_status=sp.get("review", "pending"),
        )
        session.add(o)
        lead.outreach = o
    await session.commit()
    return job.id


async def _outreach(session) -> list[Outreach]:
    return list((await session.execute(select(Outreach).order_by(Outreach.id))).scalars().all())


async def test_bulk_approve_respects_min_score(session):
    job_id = await _make_job(session, [{"score": 9.0}, {"score": 6.5}, {"score": 8.0}])
    n = await bulk_approve(session, job_id, min_score=8.0)
    assert n == 2
    statuses = [o.review_status for o in await _outreach(session)]
    assert statuses == ["approved", "pending", "approved"]


async def test_bulk_queue_only_eligible_email(session):
    job_id = await _make_job(session, [
        {"review": "approved"},                       # eligible
        {"review": "pending"},                        # not reviewed -> skip
        {"review": "approved", "flags": ["unverified_email"]},  # blocked -> skip
    ])
    result = await bulk_queue(session, job_id, "email")
    assert result == {"queued": 1, "skipped": 2}
    assert [o.send_status for o in await _outreach(session)] == ["queued", "draft", "draft"]


async def test_bulk_queue_whatsapp_requires_opt_in(session):
    job_id = await _make_job(session, [
        {"review": "approved", "opt_in": 1},
        {"review": "approved", "opt_in": 0},
    ])
    result = await bulk_queue(session, job_id, "whatsapp")
    assert result == {"queued": 1, "skipped": 1}


async def test_process_next_send_drains_queue(session):
    job_id = await _make_job(session, [{"review": "approved"}, {"review": "approved"}])
    await bulk_queue(session, job_id, "email")

    first = await process_next_send(session)
    assert first is not None and first[0] == "email"
    second = await process_next_send(session)
    assert second is not None
    # queue now empty
    assert await process_next_send(session) is None

    statuses = [o.send_status for o in await _outreach(session)]
    assert statuses == ["sent", "sent"]


async def test_email_bounce_webhook_suppresses(session):
    job_id = await _make_job(session, [{"review": "approved", "email": "bounce@corp.com"}])
    updated = await record_email_event(session, "bounce@corp.com", "bounced")
    assert updated == 1
    assert (await _outreach(session))[0].send_status == "bounced"
    assert await suppression.is_suppressed(session, "bounce@corp.com")


async def test_email_reply_webhook_marks_replied(session):
    await _make_job(session, [{"review": "approved", "email": "yes@corp.com"}])
    updated = await record_email_event(session, "yes@corp.com", "replied")
    assert updated == 1
    assert (await _outreach(session))[0].send_status == "replied"
    assert not await suppression.is_suppressed(session, "yes@corp.com")


async def test_whatsapp_event_matches_by_normalized_number(session):
    await _make_job(session, [{"review": "approved", "phone": "+1 (555) 010-0000"}])
    updated = await record_whatsapp_event(session, "15550100000", "replied")
    assert updated == 1
    assert (await _outreach(session))[0].wa_send_status == "replied"


def test_send_window_always_open_by_default():
    # default window 0..24 -> always True
    assert in_send_window() is True
