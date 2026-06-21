"""Opportunity Mapping Agent: company + role + OUR services -> outreach angle.

This is where the intelligence happens: reason about how our offering relates to this
specific lead's likely needs.
"""
from __future__ import annotations

import json

from app.agents.base import run_json_agent
from app.config import COMPANY_PROFILE
from app.schemas import CompanyResearch, Opportunity, RoleProfile

_SYSTEM = (
    "You are a B2B sales strategist for the company described below. Given a prospect's "
    "company profile and role analysis, identify the single most relevant reason this "
    "prospect would benefit from our services. Be specific and grounded; avoid generic "
    "claims. Respond ONLY with a JSON object.\n\n"
    f"OUR COMPANY:\n{json.dumps(COMPANY_PROFILE, indent=2)}"
)

_SCHEMA_HINT = '{"outreach_angle": str, "rationale": str, "relevant_services": [str]}'


async def map_opportunity(
    *, company_research: CompanyResearch, role_profile: RoleProfile
) -> Opportunity:
    user = (
        "PROSPECT COMPANY:\n"
        f"- Industry: {company_research.industry}\n"
        f"- Focus: {', '.join(company_research.focus)}\n"
        f"- Services: {', '.join(company_research.services)}\n"
        f"- Summary: {company_research.summary}\n\n"
        "PROSPECT ROLE:\n"
        f"- Role: {role_profile.role} ({role_profile.seniority})\n"
        f"- Priorities: {', '.join(role_profile.priorities)}\n"
        f"- Pain points: {', '.join(role_profile.pain_points)}\n\n"
        f"Return JSON: {_SCHEMA_HINT}\n"
        "- outreach_angle: a short phrase naming the angle (e.g. 'Workflow Automation')\n"
        "- rationale: 1-2 sentences linking their likely pain to our services\n"
        "- relevant_services: which of OUR services apply"
    )
    return await run_json_agent(
        task="opportunity",
        system=_SYSTEM,
        user=user,
        schema=Opportunity,
        temperature=0.5,
        max_tokens=600,
    )
