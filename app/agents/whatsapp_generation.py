"""WhatsApp Generation Agent: shorter, conversational, still professional."""
from __future__ import annotations

import json

from app.agents.base import run_json_agent
from app.config import merge_company_profile
from app.schemas import CompanyResearch, Opportunity, Personalization, WhatsAppContent


def _system(company_profile: dict | None) -> str:
    profile = merge_company_profile(company_profile)
    return (
        "You write short, friendly, professional WhatsApp outreach on behalf of the company "
        "below. Conversational tone, 40-70 words, no emojis overload (at most one), no links, "
        "reference the prospect's company naturally, end with a light question. Respond ONLY "
        "with JSON.\n\n"
        f"OUR COMPANY:\n{json.dumps(profile, indent=2)}"
    )


_SCHEMA_HINT = '{"message": str}'


async def generate_whatsapp(
    *,
    name: str | None,
    company_research: CompanyResearch,
    opportunity: Opportunity,
    personalization: Personalization,
    company_profile: dict | None = None,
) -> WhatsAppContent:
    user = (
        f"Recipient first name: {(name or 'there').split()[0]}\n"
        f"Company: {company_research.company}\n"
        f"Company focus: {', '.join(company_research.focus)}\n"
        f"Outreach angle: {opportunity.outreach_angle}\n"
        f"Hook: {personalization.hook}\n\n"
        f"Write the WhatsApp message. Return JSON: {_SCHEMA_HINT}"
    )
    return await run_json_agent(
        task="whatsapp",
        system=_system(company_profile),
        user=user,
        schema=WhatsAppContent,
        temperature=0.7,
        max_tokens=400,
    )
