"""Follow-up sequence engine tests (template steps → no LLM, console channels)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.channels import suppression
from app.db import Base
from app.models import Enrollment, Job, Lead, Outreach, Sequence, SequenceStep
from app.sequences import (
    enroll_lead,
    process_due_enrollments,
    process_enrollment_step,
    render_template,
    stop_enrollment,
)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _seq(session, *steps) -> Sequence:
    """steps: tuples of (channel, delay_days)."""
    seq = Sequence(name="Test seq", is_default=1, active=1)
    for i, (channel, delay) in enumerate(steps, start=1):
        seq.steps.append(SequenceStep(
            step_order=i, channel=channel, delay_days=delay, generate=0,
            subject_template="Re: {company}",
            body_template="Hi {first_name}, following up about {company}.",
        ))
    session.add(seq)
    await session.commit()
    return seq


async def _lead(session, **ov) -> Lead:
    job = Job(id="2026-06-21-001", source_filename="x.csv")
    session.add(job)
    await session.flush()
    lead = Lead(
        job_id=job.id, name="Ann Lee",
        email=ov.get("email", "ann@corp.com"),
        phone=ov.get("phone", "+1 555 0100"),
        opt_in=ov.get("opt_in", 1),
        validation_flags=ov.get("flags", []),
    )
    session.add(lead)
    await session.flush()
    o = Outreach(lead_id=lead.id, email_subject="Hi", email_body="Body",
                 whatsapp_body="Hey", review_status="approved")
    session.add(o)
    lead.outreach = o
    await session.commit()
    return lead


def test_render_template_fills_placeholders():
    lead = Lead(name="Ann Lee", company="Acme")
    out = render_template("Hi {first_name} at {company} ({name})", lead)
    assert out == "Hi Ann at Acme (Ann Lee)"


async def test_enroll_schedules_first_step(session):
    await _seq(session, ("email", 3), ("email", 5))
    lead = await _lead(session)
    enr = await enroll_lead(session, lead)
    assert enr is not None
    assert enr.status == "active"
    assert enr.current_step == 0
    assert enr.next_run_at is not None


async def test_enroll_is_idempotent(session):
    await _seq(session, ("email", 3))
    lead = await _lead(session)
    assert await enroll_lead(session, lead) is not None
    assert await enroll_lead(session, lead) is None  # already enrolled


async def test_due_step_sends_and_advances(session):
    await _seq(session, ("email", 0), ("whatsapp", 0))
    lead = await _lead(session)
    enr = await enroll_lead(session, lead)

    # First step due now.
    later = datetime.now(timezone.utc) + timedelta(seconds=1)
    outcome = await process_enrollment_step(session, enr, now=later)
    assert outcome == "sent"
    assert enr.current_step == 1
    assert enr.last_channel == "email"
    assert lead.outreach.send_status == "sent"

    # Second (final) step → completes.
    outcome = await process_enrollment_step(session, enr, now=later)
    assert outcome == "sent"
    assert enr.status == "completed"
    assert enr.next_run_at is None


async def test_reply_stops_sequence(session):
    await _seq(session, ("email", 0), ("email", 0))
    lead = await _lead(session)
    enr = await enroll_lead(session, lead)
    lead.outreach.send_status = "replied"
    await session.commit()

    outcome = await process_enrollment_step(session, enr)
    assert outcome == "stopped"
    assert enr.stop_reason == "replied"


async def test_suppression_stops_sequence(session):
    await _seq(session, ("email", 0))
    lead = await _lead(session, email="stop@corp.com")
    enr = await enroll_lead(session, lead)
    await suppression.add_suppression(session, "stop@corp.com")

    outcome = await process_enrollment_step(session, enr)
    assert outcome == "stopped"
    assert enr.stop_reason == "unsubscribed"


async def test_whatsapp_step_skipped_without_opt_in(session):
    await _seq(session, ("whatsapp", 0))
    lead = await _lead(session, opt_in=0)
    enr = await enroll_lead(session, lead)
    outcome = await process_enrollment_step(session, enr)
    assert outcome == "skipped"            # not opted in → not sent
    assert enr.status == "completed"       # but the step is consumed


async def test_process_due_only_fires_past_due(session):
    await _seq(session, ("email", 0), ("email", 30))
    lead = await _lead(session)
    enr = await enroll_lead(session, lead)
    # Make step 1 due.
    enr.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await session.commit()

    n = await process_due_enrollments(session)
    assert n == 1
    # Step 2 scheduled 30 days out → not due now.
    assert (await process_due_enrollments(session)) == 0


async def test_manual_stop(session):
    await _seq(session, ("email", 5))
    lead = await _lead(session)
    await enroll_lead(session, lead)
    assert await stop_enrollment(session, lead.id, "manual") is True
    enr = (await session.execute(select(Enrollment))).scalar_one()
    assert enr.status == "stopped" and enr.stop_reason == "manual"
