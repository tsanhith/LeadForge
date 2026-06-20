"""Company Research Agent: scraped website text -> structured company profile."""
from __future__ import annotations

from app.agents.base import run_json_agent
from app.schemas import CompanyResearch
from app.scraping.fetcher import SiteContent

_SYSTEM = (
    "You are a B2B company research analyst. Given text scraped from a company's website, "
    "extract a concise, factual profile. Only use information supported by the text; do not "
    "invent products or claims. Respond ONLY with a JSON object."
)

_SCHEMA_HINT = (
    '{"company": str, "industry": str, "focus": [str], "services": [str], '
    '"business_model": str, "keywords": [str], "summary": str}'
)


async def research_company(
    *, company: str | None, website: str | None, site: SiteContent
) -> CompanyResearch:
    if not site.available or not site.text:
        # Graceful degradation: minimal profile from the lead fields we already have.
        return CompanyResearch(
            company=company or "",
            summary="Website unavailable; limited public information.",
        )

    user = (
        f"Company name (from lead data): {company or 'unknown'}\n"
        f"Website: {site.url}\n"
        f"Page title: {site.title}\n\n"
        f"Scraped website text:\n\"\"\"\n{site.text}\n\"\"\"\n\n"
        f"Return JSON with this shape: {_SCHEMA_HINT}\n"
        "- focus: 2-5 core focus areas\n"
        "- services: concrete services/products offered\n"
        "- keywords: 5-10 terms describing the business\n"
        "- summary: 2-3 sentence plain-English overview"
    )
    return await run_json_agent(
        task="research",
        system=_SYSTEM,
        user=user,
        schema=CompanyResearch,
        temperature=0.3,
        max_tokens=900,
    )
