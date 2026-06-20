"""All HTTP / HTMX endpoints."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import get_session
from app.job_service import create_job
from app.models import Job, Lead, Outreach
from app.pipeline.orchestrator import process_lead
from app.pipeline.worker import enqueue_job

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


# ------------------------------------------------------------------ home + upload
@router.get("/", response_class=HTMLResponse)
async def home(request: Request, session: AsyncSession = Depends(get_session)):
    jobs = (
        await session.execute(select(Job).order_by(Job.created_at.desc()))
    ).scalars().all()
    totals = {
        "jobs": len(jobs),
        "leads": sum(j.total for j in jobs),
        "high_quality": sum(j.high_quality for j in jobs),
        "needs_review": sum(j.needs_review for j in jobs),
    }
    return templates.TemplateResponse(
        request, "dashboard.html", {"jobs": jobs, "totals": totals}
    )


@router.post("/upload")
async def upload(
    file: UploadFile, session: AsyncSession = Depends(get_session)
):
    settings = get_settings()
    os.makedirs(settings.upload_dir, exist_ok=True)
    ext = Path(file.filename or "upload.xlsx").suffix or ".xlsx"
    dest = Path(settings.upload_dir) / f"{uuid.uuid4().hex}{ext}"
    dest.write_bytes(await file.read())

    job = await create_job(
        session, file_path=str(dest), filename=file.filename or dest.name
    )
    enqueue_job(job.id)
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)


# ------------------------------------------------------------------ job dashboard
def _filter_leads(stmt, params: dict):
    q = (params.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            Lead.name.ilike(like)
            | Lead.company.ilike(like)
            | Lead.industry.ilike(like)
            | Lead.position.ilike(like)
        )
    if params.get("industry"):
        stmt = stmt.where(Lead.industry.ilike(f"%{params['industry']}%"))
    if params.get("position"):
        stmt = stmt.where(Lead.position.ilike(f"%{params['position']}%"))
    if params.get("review_status"):
        stmt = stmt.join(Outreach).where(Outreach.review_status == params["review_status"])
    min_score = params.get("min_score")
    if min_score:
        try:
            stmt = stmt.join(Outreach).where(Outreach.quality_score >= float(min_score))
        except ValueError:
            pass
    return stmt


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(
    job_id: str, request: Request, session: AsyncSession = Depends(get_session)
):
    job = await session.get(Job, job_id)
    if job is None:
        return HTMLResponse("Job not found", status_code=404)
    params = dict(request.query_params)
    leads = await _load_leads(session, job_id, params)
    return templates.TemplateResponse(
        request,
        "job.html",
        {"job": job, "leads": leads, "params": params, "settings": get_settings()},
    )


@router.get("/jobs/{job_id}/leads", response_class=HTMLResponse)
async def job_leads_partial(
    job_id: str, request: Request, session: AsyncSession = Depends(get_session)
):
    """HTMX partial: the lead table + live stats (used for search/filter and polling)."""
    job = await session.get(Job, job_id)
    if job is None:
        return HTMLResponse("Job not found", status_code=404)
    params = dict(request.query_params)
    leads = await _load_leads(session, job_id, params)
    return templates.TemplateResponse(
        request,
        "partials/lead_table.html",
        {"job": job, "leads": leads, "params": params, "settings": get_settings()},
    )


async def _load_leads(session: AsyncSession, job_id: str, params: dict):
    stmt = (
        select(Lead)
        .where(Lead.job_id == job_id)
        .options(selectinload(Lead.outreach))
        .order_by(Lead.id)
    )
    stmt = _filter_leads(stmt, params)
    return (await session.execute(stmt)).scalars().unique().all()


# ------------------------------------------------------------------ lead review
@router.get("/leads/{lead_id}", response_class=HTMLResponse)
async def lead_review(
    lead_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    lead = await session.get(Lead, lead_id, options=[selectinload(Lead.outreach)])
    if lead is None:
        return HTMLResponse("Lead not found", status_code=404)
    return templates.TemplateResponse(request, "lead_review.html", {"lead": lead})


@router.post("/leads/{lead_id}/approve", response_class=HTMLResponse)
async def lead_approve(
    lead_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    lead = await session.get(Lead, lead_id, options=[selectinload(Lead.outreach)])
    if lead and lead.outreach:
        lead.outreach.review_status = "approved"
        await session.commit()
    return templates.TemplateResponse(request, "partials/review_panel.html", {"lead": lead})


@router.post("/leads/{lead_id}/edit", response_class=HTMLResponse)
async def lead_edit(
    lead_id: int,
    request: Request,
    email_subject: str = Form(""),
    email_body: str = Form(""),
    whatsapp_body: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    lead = await session.get(Lead, lead_id, options=[selectinload(Lead.outreach)])
    if lead and lead.outreach:
        lead.outreach.email_subject = email_subject
        lead.outreach.email_body = email_body
        lead.outreach.whatsapp_body = whatsapp_body
        lead.outreach.review_status = "edited"
        await session.commit()
    return templates.TemplateResponse(request, "partials/review_panel.html", {"lead": lead})


@router.post("/leads/{lead_id}/regenerate", response_class=HTMLResponse)
async def lead_regenerate(
    lead_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    lead = await session.get(Lead, lead_id, options=[selectinload(Lead.outreach)])
    if lead:
        await process_lead(session, lead)
        await session.refresh(lead, attribute_names=["outreach"])
    return templates.TemplateResponse(request, "partials/review_panel.html", {"lead": lead})
