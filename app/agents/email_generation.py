"""Email Generation Agent: unique, personalized cold email. No templates, no mail merge."""
from __future__ import annotations

import json

from app.agents.base import run_json_agent
from app.config import merge_company_profile
from app.schemas import (
    CompanyResearch,
    EmailContent,
    Opportunity,
    Personalization,
    RoleProfile,
)


def _system(company_profile: dict | None) -> str:
    profile = merge_company_profile(company_profile)
    sign = profile.get("sender_name") or "the team"
    return (
        "You are an expert B2B copywriter writing on behalf of the company below. Write a "
        "short, genuinely personalized cold email (90-150 words). Reference the prospect's "
        "company and role naturally. No fluff, no buzzword soup, no fake personal claims, no "
        f"placeholders like [Name]. Sign off as {sign}. End with a soft, low-friction call to "
        "action. Respond ONLY with JSON.\n\n"
        f"OUR COMPANY:\n{json.dumps(profile, indent=2)}"
    )


_SCHEMA_HINT = '{"subject": str, "body": str}'


async def generate_email(
    *,
    name: str | None,
    position: str | None,
    company_research: CompanyResearch,
    role_profile: RoleProfile,
    opportunity: Opportunity,
    personalization: Personalization,
    company_profile: dict | None = None,
) -> EmailContent:
    user = (
        f"Recipient: {name or 'there'} — {position or ''} at {company_research.company}\n"
        f"Industry: {company_research.industry}\n"
        f"Outreach angle: {opportunity.outreach_angle}\n"
        f"Why relevant: {opportunity.rationale}\n"
        f"Hook: {personalization.hook}\n"
        f"Talking points: {', '.join(personalization.talking_points)}\n\n"
        f"Write the email. Return JSON: {_SCHEMA_HINT}\n"
        "- subject: specific to their company, not generic\n"
        "- body: greeting using their first name, personalized, signed off as instructed"
    )
    return await run_json_agent(
        task="email",
        system=_system(company_profile),
        user=user,
        schema=EmailContent,
        temperature=0.7,
        max_tokens=700,
    )
