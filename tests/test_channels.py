"""Channel-layer unit tests (no network — console provider + pure helpers)."""
from __future__ import annotations

from app.channels import email as email_channel
from app.channels import whatsapp as whatsapp_channel


def test_unsubscribe_footer_has_link_and_address():
    body = email_channel.with_unsubscribe_footer("Hi there.", "lead@corp.com")
    assert "Hi there." in body
    assert "/unsubscribe?email=lead%40corp.com" in body  # url-encoded
    # the configured postal address must appear (CAN-SPAM)
    from app.config import get_settings
    assert get_settings().company_postal_address in body


async def test_console_email_send_ok():
    result = await email_channel.send_email("a@b.com", "Subject", "Body")
    assert result.ok
    assert result.provider == "console"
    assert result.message_id


async def test_console_whatsapp_send_ok():
    result = await whatsapp_channel.send_whatsapp("+1 (555) 010-2030", "Hello")
    assert result.ok
    assert result.provider == "console"


def test_normalize_msisdn_strips_non_digits():
    assert whatsapp_channel.normalize_msisdn("+91 91776 22213") == "919177622213"
    assert whatsapp_channel.normalize_msisdn("") == ""
