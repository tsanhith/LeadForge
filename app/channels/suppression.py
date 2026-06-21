"""Do-not-contact (suppression) list helpers.

Checked before every email send and written to by the unsubscribe endpoint / bounce
handling. Keyed by lowercased email so one opt-out applies everywhere, forever.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Suppression


def _norm(email: str) -> str:
    return (email or "").strip().lower()


async def is_suppressed(session: AsyncSession, email: str | None) -> bool:
    if not email:
        return False
    row = (
        await session.execute(
            select(Suppression.id).where(Suppression.email == _norm(email))
        )
    ).first()
    return row is not None


async def add_suppression(
    session: AsyncSession, email: str, reason: str = "unsubscribe"
) -> bool:
    """Add an email to the suppression list. Returns False if already present."""
    norm = _norm(email)
    if not norm:
        return False
    if await is_suppressed(session, norm):
        return False
    session.add(Suppression(email=norm, reason=reason))
    await session.commit()
    return True
