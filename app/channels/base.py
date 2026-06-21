"""Shared types for outreach channels."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SendResult:
    """Outcome of a single delivery attempt.

    ``ok`` is the only field the caller must branch on. ``message_id`` is the provider's id
    (used for later open/reply tracking); ``error`` is a short human-readable reason on
    failure. ``provider`` records which backend handled it (incl. "console" for the mock).
    """

    ok: bool
    provider: str
    message_id: str | None = None
    error: str | None = None
