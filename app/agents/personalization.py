"""Personalization Agent: consolidate everything into the master prospect context."""
from __future__ import annotations

from app.agents.base import run_json_agent
from app.schemas import CompanyResearch, Opportunity, Personalization, RoleProfile

_SYSTEM = (
    "You build a tight 'master context' brief that a writer will use to craft personalized "
    "outreach. Synthesize the inputs into the most compelling, specific hook for this exact "
    "person. Respond ONLY with a JSON object."
)

_SCHEMA_HINT = (
    '{"potential_interest": str, "hook": str, "talking_points": [str], "summary": str}'
)


async def personalize(
    *,
    name: str | None,
    position: str | None,
    company_research: CompanyResearch,
    role_profile: RoleProfile,
    opportunity: Opportunity,
) -> Personalization:
    user = (
        f"Lead: {name or 'unknown'} — {position or 'unknown'}\n"
        f"Company: {company_research.company} ({company_research.industry})\n"
        f"Outreach angle: {opportunity.outreach_angle}\n"
        f"Rationale: {opportunity.rationale}\n"
        f"Role priorities: {', '.join(role_profile.priorities)}\n\n"
        f"Return JSON: {_SCHEMA_HINT}\n"
        "- potential_interest: the one thing they'd most likely want to hear about\n"
        "- hook: a specific opening observation tied to their company\n"
        "- talking_points: 2-4 concrete points to weave into outreach\n"
        "- summary: 2 sentence brief for the writer"
    )
    return await run_json_agent(
        task="personalize",
        system=_SYSTEM,
        user=user,
        schema=Personalization,
        temperature=0.5,
        max_tokens=600,
    )
