"""User CRUD + authentication + first-run admin seeding."""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password, verify_password
from app.config import get_settings
from app.db import SessionLocal
from app.models import User

logger = logging.getLogger("leadforge.auth")


def _norm(email: str) -> str:
    return (email or "").strip().lower()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return (
        await session.execute(select(User).where(User.email == _norm(email)))
    ).scalar_one_or_none()


async def create_user(
    session: AsyncSession, *, email: str, password: str, role: str = "member"
) -> User:
    user = User(email=_norm(email), password_hash=hash_password(password), role=role, active=1)
    session.add(user)
    await session.commit()
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    user = await get_user_by_email(session, email)
    if user is None or not user.active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def seed_admin() -> None:
    """Create the admin from ADMIN_EMAIL/ADMIN_PASSWORD if there are no users yet."""
    s = get_settings()
    async with SessionLocal() as session:
        count = (await session.execute(select(func.count()).select_from(User))).scalar_one()
        if count:
            return
        if not (s.admin_email and s.admin_password):
            logger.warning(
                "no users exist and ADMIN_EMAIL/ADMIN_PASSWORD are unset — "
                "set them in .env to create the first admin"
            )
            return
        await create_user(
            session, email=s.admin_email, password=s.admin_password, role="admin"
        )
        logger.info("seeded admin user %s", _norm(s.admin_email))
