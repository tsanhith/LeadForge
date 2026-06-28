"""Follow-up Generation Agent: a short nudge for a lead who hasn't replied.

Given the original outreach context and which follow-up number this is, it writes a brief,
non-pushy message that adds a little value and references the prior note — never a copy-paste
"just bumping this". Used by the sequence scheduler for steps marked ``generate``.
"""
from __future__ import annotations

import json

from app.agents.base import run_json_agent
from app.config import merge_company_profile
from app.schemas import FollowUpContent


def _system(company_profile: dict | None) -> str:
    profile = merge_company_profile(company_profile)
    return (
        "You write short, polite B2B follow-up messages on behalf of the company below, to a "
        "prospect who received an earlier message and has not replied. Rules: reference the "
        "earlier outreach naturally, add one small piece of value or a soft reason to reply, "
        "stay under 80 words, no guilt-tripping, no 'just bumping this', vary the wording from "
        "a typical follow-up. Respond ONLY with JSON.\n\n"
        f"OUR COMPANY:\n{json.dumps(profile, indent=2)}"
    )


async def generate_followup(
    *,
    channel: str,
    follow_up_number: int,
    name: str | None,
    company: str | None,
    position: str | None,
    original_subject: str | None,
    original_body: str | None,
    outreach_angle: str | None,
    company_profile: dict | None = None,
) -> FollowUpContent:
    schema_hint = (
        '{"message": str}' if channel == "whatsapp" else '{"subject": str, "message": str}'
    )
    user = (
        f"Channel: {channel}\n"
        f"This is follow-up #{follow_up_number} (they have not replied to earlier messages).\n"
        f"Recipient first name: {(name or 'there').split()[0]}\n"
        f"Their role: {position or 'unknown'}\n"
        f"Their company: {company or 'their company'}\n"
        f"Original angle: {outreach_angle or ''}\n"
        f"Original subject: {original_subject or ''}\n"
        f"Original message (for context, do not repeat verbatim):\n{(original_body or '')[:600]}\n\n"
        f"Write the follow-up. Return JSON: {schema_hint}"
    )
    return await run_json_agent(
        task="followup",
        system=_system(company_profile),
        user=user,
        schema=FollowUpContent,
        temperature=0.7,
        max_tokens=300,
    )
