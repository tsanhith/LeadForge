"""Per-user company profile: resolution logic + it actually reaching the pipeline."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import COMPANY_PROFILE, merge_company_profile
from app.db import Base
from app.job_service import create_job  # noqa: F401  (ensures model import side-effects)
from app.models import Job, User


def test_merge_uses_default_when_unset():
    assert merge_company_profile(None) == COMPANY_PROFILE
    assert merge_company_profile({}) == COMPANY_PROFILE
    # a profile with no name is treated as unconfigured -> default
    assert merge_company_profile({"one_liner": "x"}) == COMPANY_PROFILE


def test_merge_replaces_fully_when_named():
    profile = {
        "name": "Acme Robotics",
        "one_liner": "We automate warehouses.",
        "services": ["Pick-and-place arms", "Fleet software"],
        "value_props": ["Fewer injuries", "24/7 throughput"],
        "sender_name": "Dana",
        "website": "https://acme.example",
    }
    merged = merge_company_profile(profile)
    assert merged["name"] == "Acme Robotics"
    assert merged["services"] == ["Pick-and-place arms", "Fleet software"]
    assert merged["sender_name"] == "Dana"
    # no LeadForge default leaks through
    assert "LeadForge" not in merged["name"]
    assert merged["value_props"] == ["Fewer injuries", "24/7 throughput"]


def test_merge_tolerates_missing_list_fields():
    merged = merge_company_profile({"name": "Solo Co"})
    assert merged["name"] == "Solo Co"
    assert merged["services"] == []
    assert merged["value_props"] == []


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        yield s
    await engine.dispose()


async def test_job_company_profile_follows_uploader(session: AsyncSession):
    from app.pipeline.worker import _job_company_profile

    user = User(email="ops@acme.example", password_hash="x", role="member",
                company_profile={"name": "Acme", "services": ["arms"]})
    session.add(user)
    await session.commit()

    job = Job(id="2026-01-01-001", source_filename="f.csv", status="processing", user_id=user.id)
    session.add(job)
    await session.commit()

    profile = await _job_company_profile(session, job.id)
    assert profile == {"name": "Acme", "services": ["arms"]}

    # a job with no uploader falls back to the default (None -> default in agents)
    orphan = Job(id="2026-01-01-002", source_filename="f.csv", status="processing")
    session.add(orphan)
    await session.commit()
    assert await _job_company_profile(session, orphan.id) is None
