"""ORM models: Job -> Lead -> Outreach.

Intermediate agent outputs are stored as JSON columns on Lead so the pipeline can persist
progress step-by-step and the review UI can show every stage of reasoning.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Job(Base):
    __tablename__ = "jobs"

    # Human-readable id like 2026-06-20-001.
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    source_filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="processing")  # processing|done|failed

    total: Mapped[int] = mapped_column(Integer, default=0)        # valid leads queued
    processed: Mapped[int] = mapped_column(Integer, default=0)
    high_quality: Mapped[int] = mapped_column(Integer, default=0)
    needs_review: Mapped[int] = mapped_column(Integer, default=0)
    invalid: Mapped[int] = mapped_column(Integer, default=0)      # rows dropped at validation

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    leads: Mapped[list["Lead"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)

    # Normalized lead fields.
    name: Mapped[str | None] = mapped_column(String(255))
    position: Mapped[str | None] = mapped_column(String(255))
    company: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(512))
    linkedin: Mapped[str | None] = mapped_column(String(512))
    industry: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)

    # Pipeline status: pending|processing|done|failed
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text)

    # Consent for WhatsApp outreach. Meta policy forbids cold-messaging non-opted-in
    # contacts on the first touch; the WhatsApp send guard enforces this.
    opt_in: Mapped[bool] = mapped_column(Integer, default=0)

    # Validation notes (e.g. ["missing_website", "invalid_email"]).
    validation_flags: Mapped[list] = mapped_column(JSON, default=list)

    # Stage outputs (JSON dicts) — populated as the pipeline runs.
    company_research: Mapped[dict | None] = mapped_column(JSON)
    role_profile: Mapped[dict | None] = mapped_column(JSON)
    opportunity: Mapped[dict | None] = mapped_column(JSON)
    personalization: Mapped[dict | None] = mapped_column(JSON)

    job: Mapped["Job"] = relationship(back_populates="leads")
    outreach: Mapped["Outreach | None"] = relationship(
        back_populates="lead", cascade="all, delete-orphan", uselist=False
    )


class Outreach(Base):
    __tablename__ = "outreach"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), unique=True, index=True
    )

    email_subject: Mapped[str | None] = mapped_column(String(512))
    email_body: Mapped[str | None] = mapped_column(Text)
    whatsapp_body: Mapped[str | None] = mapped_column(Text)

    quality_score: Mapped[float | None] = mapped_column(Float, index=True)
    qa_feedback: Mapped[dict | None] = mapped_column(JSON)  # checklist + notes

    # pending|approved|edited
    review_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)

    # --- Email send tracking ---
    # draft|queued|sent|failed|suppressed|bounced|replied
    send_status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    send_error: Mapped[str | None] = mapped_column(Text)

    # --- WhatsApp send tracking ---
    wa_send_status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    wa_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    wa_provider_message_id: Mapped[str | None] = mapped_column(String(255))
    wa_send_error: Mapped[str | None] = mapped_column(Text)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    lead: Mapped["Lead"] = relationship(back_populates="outreach")


class Suppression(Base):
    """Do-not-contact list. Checked before every email send (CAN-SPAM / GDPR).

    Populated by the unsubscribe endpoint and by bounce/complaint handling. Keyed by
    lowercased email so a one-time opt-out applies across all jobs and future uploads.
    """

    __tablename__ = "suppressions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    reason: Mapped[str] = mapped_column(String(64), default="unsubscribe")  # unsubscribe|bounce|complaint|manual
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
