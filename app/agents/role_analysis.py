"""Role Analysis Agent: position -> likely priorities, pain points, tech adoption."""
from __future__ import annotations

from app.agents.base import run_json_agent
from app.schemas import CompanyResearch, RoleProfile

_SYSTEM = (
    "You analyze a person's job role to infer what they likely care about at work. "
    "Tailor the analysis to the company's industry. Respond ONLY with a JSON object."
)

_SCHEMA_HINT = (
    '{"role": str, "seniority": str, "priorities": [str], "pain_points": [str], '
    '"tech_adoption": str}'
)


async def analyze_role(
    *, position: str | None, company_research: CompanyResearch
) -> RoleProfile:
    user = (
        f"Position: {position or 'unknown'}\n"
        f"Company industry: {company_research.industry or 'unknown'}\n"
        f"Company focus: {', '.join(company_research.focus) or 'unknown'}\n\n"
        f"Infer this person's professional priorities and likely operational pain points. "
        f"Return JSON: {_SCHEMA_HINT}\n"
        "- seniority: e.g. C-level, VP, manager, individual contributor\n"
        "- priorities: 3-5 things this role typically optimizes for\n"
        "- pain_points: 3-5 recurring frustrations for this role in this industry\n"
        "- tech_adoption: one sentence on how open this role likely is to new technology"
    )
    return await run_json_agent(
        task="role",
        system=_SYSTEM,
        user=user,
        schema=RoleProfile,
        temperature=0.4,
        max_tokens=700,
    )
