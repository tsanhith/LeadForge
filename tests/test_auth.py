"""Auth: password hashing + authentication + recovery collection."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.security import hash_password, verify_password
from app.auth.service import authenticate, create_user, get_user_by_email
from app.db import Base
from app.models import Job, Lead
from app.pipeline.queue import reset_and_collect


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


def test_hash_roundtrip_and_uniqueness():
    h1 = hash_password("hunter2")
    h2 = hash_password("hunter2")
    assert h1 != h2                      # different salts
    assert verify_password("hunter2", h1)
    assert not verify_password("wrong", h1)


def test_verify_rejects_garbage():
    assert not verify_password("x", "not-a-valid-hash")
    assert not verify_password("x", "")


async def test_authenticate(session):
    await create_user(session, email="Admin@Corp.com", password="s3cret", role="admin")
    # email normalized to lowercase
    assert await get_user_by_email(session, "admin@corp.com") is not None
    assert await authenticate(session, "admin@corp.com", "s3cret") is not None
    assert await authenticate(session, "admin@corp.com", "nope") is None
    assert await authenticate(session, "ghost@corp.com", "s3cret") is None


async def test_inactive_user_cannot_authenticate(session):
    user = await create_user(session, email="x@y.com", password="pw")
    user.active = 0
    await session.commit()
    assert await authenticate(session, "x@y.com", "pw") is None


async def test_recovery_resets_leads_and_collects_jobs(session):
    done = Job(id="j-done", source_filename="a", status="done")
    proc = Job(id="j-proc", source_filename="b", status="processing")
    session.add_all([done, proc])
    await session.flush()
    session.add_all([
        Lead(job_id=proc.id, status="processing"),  # interrupted -> should reset
        Lead(job_id=proc.id, status="pending"),
        Lead(job_id=done.id, status="done"),
    ])
    await session.commit()

    job_ids = await reset_and_collect(session)
    assert job_ids == ["j-proc"]                       # done job excluded
    from sqlalchemy import select
    statuses = [
        r for r in (await session.execute(select(Lead.status).where(Lead.job_id == "j-proc"))).scalars()
    ]
    assert sorted(statuses) == ["pending", "pending"]  # the processing lead was reset
