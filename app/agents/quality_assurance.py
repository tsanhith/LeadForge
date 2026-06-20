"""Quality Assurance Agent: a second LLM critiques the generated outreach.

Routed (via config) to a different model from the generators so the review is independent.
"""
from __future__ import annotations

from app.agents.base import run_json_agent
from app.schemas import CompanyResearch, EmailContent, QAReview, WhatsAppContent

_SYSTEM = (
    "You are a strict QA reviewer for sales outreach. Evaluate the email and WhatsApp message "
    "against the prospect's real details. Be honest and critical. Score 0-10 where 10 is "
    "flawless, highly personalized, and ready to send. Respond ONLY with a JSON object."
)

_SCHEMA_HINT = (
    '{"quality_score": number, "mentions_company": bool, "mentions_role": bool, '
    '"relevant": bool, "generic": bool, "grammar_ok": bool, "professional_tone": bool, '
    '"feedback": str}'
)


async def review_outreach(
    *,
    position: str | None,
    company_research: CompanyResearch,
    email: EmailContent,
    whatsapp: WhatsAppContent,
) -> QAReview:
    user = (
        f"PROSPECT — company: {company_research.company}, industry: "
        f"{company_research.industry}, role: {position or 'unknown'}\n\n"
        f"EMAIL SUBJECT: {email.subject}\n"
        f"EMAIL BODY:\n{email.body}\n\n"
        f"WHATSAPP:\n{whatsapp.message}\n\n"
        "Evaluate against these checks and return JSON: " + _SCHEMA_HINT + "\n"
        "- mentions_company: does the copy reference the prospect's company?\n"
        "- mentions_role: does it speak to their role/priorities?\n"
        "- relevant: is the value proposition relevant to them?\n"
        "- generic: would this read as a mass template? (true = bad)\n"
        "- grammar_ok / professional_tone: quality checks\n"
        "- feedback: one or two sentences on the biggest issue or strength"
    )
    return await run_json_agent(
        task="qa",
        system=_SYSTEM,
        user=user,
        schema=QAReview,
        temperature=0.2,
        max_tokens=500,
    )
