"""Throwaway: run ONE Apollo lead fully end-to-end (real LLM calls) → send via console.

Mirrors the production load pattern (fresh session per lead, eager-loaded outreach).
Usage:  PYTHONPATH=. python scripts/e2e_one.py "<path-to-apollo.csv>"
"""
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.ingest.excel import parse_file
from app.ingest.validator import validate_rows
from app.models import Job, Lead
from app.pipeline.orchestrator import process_lead
from app.send_service import send_email_for_lead, send_whatsapp_for_lead

CSV = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\abhi\Downloads\apollo-contacts-export.csv"
FIELDS = ("name", "position", "company", "website", "linkedin",
          "industry", "email", "phone", "description")


async def main():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    mk = async_sessionmaker(eng, expire_on_commit=False)

    v = next(x for x in validate_rows(parse_file(CSV)) if x.valid)

    async with mk() as s:
        job = Job(id="t-001", source_filename="apollo.csv")
        s.add(job)
        await s.flush()
        s.add(Lead(job_id=job.id, validation_flags=v.flags, **{f: v.data.get(f) for f in FIELDS}))
        await s.commit()

    # Fresh session, eager-load outreach — exactly like the worker.
    async with mk() as s:
        lead = (await s.execute(
            select(Lead).options(selectinload(Lead.outreach)).limit(1)
        )).scalar_one()
        print("LEAD:", lead.name, "|", lead.company, "|", lead.email, "|", lead.phone)

        await process_lead(s, lead)
        print("PIPELINE status:", lead.status)
        o = lead.outreach
        if o:
            print("  score   :", o.quality_score)
            print("  subject :", o.email_subject)
            print("  email   :", (o.email_body or "")[:140].replace("\n", " "))
            print("  whatsapp:", (o.whatsapp_body or "")[:140].replace("\n", " "))
            o.review_status = "approved"
            await s.commit()
            print("SEND email   :", (await send_email_for_lead(s, lead)).message, "->", o.send_status)
            lead.opt_in = 1
            await s.commit()
            print("SEND whatsapp:", (await send_whatsapp_for_lead(s, lead)).message, "->", o.wa_send_status)
    await eng.dispose()


asyncio.run(main())
