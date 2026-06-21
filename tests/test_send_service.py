"""Send-service guard tests against an in-memory database (console provider)."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.channels import suppression
from app.db import Base
from app.models import Job, Lead, Outreach
from app.send_service import send_email_for_lead, send_whatsapp_for_lead


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _make_lead(session, **overrides):
    job = Job(id="2026-06-21-001", source_filename="x.csv")
    session.add(job)
    lead = Lead(
        job_id=job.id,
        name="Ann Lee",
        email=overrides.get("email", "ann@corp.com"),
        phone=overrides.get("phone", "+1 555 0100"),
        validation_flags=overrides.get("flags", []),
        opt_in=overrides.get("opt_in", 0),
    )
    session.add(lead)
    await session.flush()
    o = Outreach(
        lead_id=lead.id,
        email_subject="Hi",
        email_body="Body",
        whatsapp_body="Hey",
        review_status=overrides.get("review_status", "approved"),
    )
    session.add(o)
    lead.outreach = o
    await session.commit()
    return lead


async def test_email_blocked_until_approved(session):
    lead = await _make_lead(session, review_status="pending")
    outcome = await send_email_for_lead(session, lead)
    assert not outcome.ok
    assert lead.outreach.send_status != "sent"


async def test_email_sent_when_approved(session):
    lead = await _make_lead(session, review_status="approved")
    outcome = await send_email_for_lead(session, lead)
    assert outcome.ok
    assert lead.outreach.send_status == "sent"
    assert lead.outreach.sent_at is not None
    assert lead.outreach.provider_message_id


async def test_email_blocked_for_unverified_flag(session):
    lead = await _make_lead(session, flags=["unverified_email"])
    outcome = await send_email_for_lead(session, lead)
    assert not outcome.ok
    assert lead.outreach.send_status == "failed"


async def test_email_blocked_when_suppressed(session):
    lead = await _make_lead(session, email="stop@corp.com")
    await suppression.add_suppression(session, "stop@corp.com")
    outcome = await send_email_for_lead(session, lead)
    assert not outcome.ok
    assert lead.outreach.send_status == "suppressed"


async def test_whatsapp_requires_opt_in(session):
    lead = await _make_lead(session, opt_in=0)
    outcome = await send_whatsapp_for_lead(session, lead)
    assert not outcome.ok
    assert lead.outreach.wa_send_status != "sent"


async def test_whatsapp_sent_when_opted_in(session):
    lead = await _make_lead(session, opt_in=1)
    outcome = await send_whatsapp_for_lead(session, lead)
    assert outcome.ok
    assert lead.outreach.wa_send_status == "sent"
