"""Outreach delivery channels.

Each channel exposes a single async ``send_*`` coroutine returning a :class:`SendResult`,
mirroring the spirit of the LLM gateway: the rest of the app calls one function and never
knows (or cares) which provider actually delivered the message. Providers are selected by
config, defaulting to ``console`` so the flow runs end-to-end before real credentials exist.
"""
from app.channels.base import SendResult

__all__ = ["SendResult"]
