"""Run the full agent pipeline for a single lead, persisting after each stage.

Stage order (per spec):
  Company Research -> Role Analysis -> Opportunity Mapping -> Personalization
  -> Email Generation -> WhatsApp Generation -> QA Review

Each stage's output is saved immediately so partial progress survives a crash and the review
UI can show every step. A failure marks the *lead* failed without affecting the job.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import (
    company_research as research_agent,
    email_generation,
    opportunity_mapping,
    personalization as personalization_agent,
    quality_assurance,
    role_analysis,
    whatsapp_generation,
)
from app.models import Lead, Outreach
from app.schemas import (
    CompanyResearch,
    EmailContent,
    Opportunity,
    Personalization,
    RoleProfile,
    WhatsAppContent,
)
from app.scraping.fetcher import fetch_site

logger = logging.getLogger("leadforge.pipeline")


async def process_lead(session: AsyncSession, lead: Lead) -> Lead:
    """Run all agents for one lead. Commits progress as it goes."""
    lead.status = "processing"
    lead.error = None
    await session.commit()

    try:
        # 1. Company research (live website scrape -> structured profile).
        site = await fetch_site(lead.website)
        company = await research_agent.research_company(
            company=lead.company, website=lead.website, site=site
        )
        lead.company_research = company.model_dump()
        await session.commit()

        # 2. Role analysis.
        role = await role_analysis.analyze_role(
            position=lead.position, company_research=company
        )
        lead.role_profile = role.model_dump()
        await session.commit()

        # 3. Opportunity mapping (against OUR services).
        opportunity = await opportunity_mapping.map_opportunity(
            company_research=company, role_profile=role
        )
        lead.opportunity = opportunity.model_dump()
        await session.commit()

        # 4. Personalization (master context).
        personalization = await personalization_agent.personalize(
            name=lead.name,
            position=lead.position,
            company_research=company,
            role_profile=role,
            opportunity=opportunity,
        )
        lead.personalization = personalization.model_dump()
        await session.commit()

        # 5. Email generation.
        email = await email_generation.generate_email(
            name=lead.name,
            position=lead.position,
            company_research=company,
            role_profile=role,
            opportunity=opportunity,
            personalization=personalization,
        )

        # 6. WhatsApp generation.
        whatsapp = await whatsapp_generation.generate_whatsapp(
            name=lead.name,
            company_research=company,
            opportunity=opportunity,
            personalization=personalization,
        )

        # 7. QA review (second model).
        qa = await quality_assurance.review_outreach(
            position=lead.position,
            company_research=company,
            email=email,
            whatsapp=whatsapp,
        )

        await _save_outreach(session, lead, email, whatsapp, qa)
        lead.status = "done"
        await session.commit()
        logger.info("lead %s done (score=%.1f)", lead.id, qa.quality_score)

    except Exception as exc:  # noqa: BLE001 — isolate per-lead failures
        await session.rollback()
        lead.status = "failed"
        lead.error = str(exc)[:1000]
        await session.commit()
        logger.exception("lead %s failed", lead.id)

    return lead


async def _save_outreach(
    session: AsyncSession,
    lead: Lead,
    email: EmailContent,
    whatsapp: WhatsAppContent,
    qa,
) -> None:
    outreach = lead.outreach or Outreach(lead_id=lead.id)
    outreach.email_subject = email.subject
    outreach.email_body = email.body
    outreach.whatsapp_body = whatsapp.message
    outreach.quality_score = qa.quality_score
    outreach.qa_feedback = qa.model_dump()
    if outreach.id is None:
        session.add(outreach)
    lead.outreach = outreach
