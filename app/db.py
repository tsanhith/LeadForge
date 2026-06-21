"""Async SQLAlchemy engine/session setup (SQLite)."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

logger = logging.getLogger("leadforge.db")

# Columns added after the initial schema. SQLite's create_all() only creates *new* tables,
# never alters existing ones, so we add these by hand on startup (idempotent). Keep in sync
# with app.models. Format: table -> [(column, column DDL)].
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "leads": [
        ("opt_in", "INTEGER DEFAULT 0"),
    ],
    "outreach": [
        ("send_status", "VARCHAR(20) DEFAULT 'draft'"),
        ("sent_at", "DATETIME"),
        ("provider_message_id", "VARCHAR(255)"),
        ("send_error", "TEXT"),
        ("wa_send_status", "VARCHAR(20) DEFAULT 'draft'"),
        ("wa_sent_at", "DATETIME"),
        ("wa_provider_message_id", "VARCHAR(255)"),
        ("wa_send_error", "TEXT"),
    ],
}


class Base(DeclarativeBase):
    pass


_settings = get_settings()
engine = create_async_engine(_settings.database_url, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    # Import models so they register on Base.metadata before create_all.
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _add_missing_columns(conn)


async def _add_missing_columns(conn) -> None:
    """Add columns introduced after the initial schema to a pre-existing SQLite DB."""
    for table, columns in _ADDED_COLUMNS.items():
        existing = {
            row[1]
            for row in (await conn.execute(text(f"PRAGMA table_info({table})"))).all()
        }
        if not existing:  # table created fresh by create_all -> already has all columns
            continue
        for name, ddl in columns:
            if name not in existing:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                logger.info("migrated: added %s.%s", table, name)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
