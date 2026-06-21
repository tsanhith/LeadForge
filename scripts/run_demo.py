"""End-to-end demo run: ingest demo_leads.xlsx, process every lead, print results.

Exercises the real pipeline (live website scraping + LLM gateway) outside the web server.
Usage: python scripts/run_demo.py
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import SessionLocal, init_db
from app.job_service import create_job
from app.models import Lead
from app.pipeline.orchestrator import process_lead

logging.basicConfig(level=logging.WARNING)  # keep gateway noise down for readable output

LINE = "=" * 78


async def main() -> None:
    await init_db()

    async with SessionLocal() as s:
        job = await create_job(s, file_path="demo_leads.xlsx", filename="demo_leads.xlsx")
        job_id = job.id
        lead_ids = [l.id for l in job.leads]
        print(f"\nJob {job_id}: {job.total} valid leads queued, {job.invalid} invalid row(s) dropped\n")

    for lid in lead_ids:
        async with SessionLocal() as s:
            lead = await s.get(Lead, lid, options=[selectinload(Lead.outreach)])
            await process_lead(s, lead)

    # Report.
    async with SessionLocal() as s:
        leads = (
            await s.execute(
                select(Lead).where(Lead.job_id == job_id)
                .options(selectinload(Lead.outreach)).order_by(Lead.id)
            )
        ).scalars().all()

        for lead in leads:
            print(LINE)
            print(f"{lead.name}  |  {lead.position}  |  {lead.company}  ({lead.industry})")
            if lead.validation_flags:
                print(f"  flags: {lead.validation_flags}")
            print(f"  status: {lead.status}")
            if lead.error:
                print(f"  error: {lead.error}")
            if lead.company_research:
                print(f"\n  RESEARCH: {lead.company_research.get('summary','')}")
                print(f"    focus: {', '.join(lead.company_research.get('focus', []))}")
            if lead.opportunity:
                print(f"\n  ANGLE: {lead.opportunity.get('outreach_angle','')}")
                print(f"    why: {lead.opportunity.get('rationale','')}")
            o = lead.outreach
            if o:
                print(f"\n  EMAIL SUBJECT: {o.email_subject}")
                print(f"  EMAIL BODY:\n{_indent(o.email_body)}")
                print(f"\n  WHATSAPP:\n{_indent(o.whatsapp_body)}")
                print(f"\n  QA SCORE: {o.quality_score}/10")
                if o.qa_feedback:
                    print(f"    feedback: {o.qa_feedback.get('feedback','')}")
            print()

        done = [l for l in leads if l.status == "done"]
        scores = [l.outreach.quality_score for l in done if l.outreach and l.outreach.quality_score is not None]
        print(LINE)
        print(f"SUMMARY: {len(done)}/{len(leads)} processed OK; "
              f"avg quality {sum(scores)/len(scores):.1f}/10" if scores else "no scores")


def _indent(text: str | None, pad: str = "    ") -> str:
    if not text:
        return f"{pad}(none)"
    return "\n".join(pad + line for line in text.splitlines())


if __name__ == "__main__":
    asyncio.run(main())
