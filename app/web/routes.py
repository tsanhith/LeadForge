"""All HTTP / HTMX endpoints."""
from __future__ import annotations

import csv
import html
import io
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.channels import suppression
from app.config import get_settings
from app.db import get_session
from app.job_service import create_job
from app.models import Job, Lead, Outreach
from app.pipeline.orchestrator import process_lead
from app.pipeline.worker import enqueue_job
from app.send_service import (
    bulk_approve,
    bulk_queue,
    record_email_event,
    record_whatsapp_event,
    send_email_for_lead,
    send_whatsapp_for_lead,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _panel(request: Request, lead):
    """Render the review panel partial with the context it needs (lead + settings)."""
    return templates.TemplateResponse(
        request, "partials/review_panel.html", {"lead": lead, "settings": get_settings()}
    )


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


async def _count_queued(session: AsyncSession, job_id: str) -> int:
    """How many of this job's messages are waiting in the throttled send queue."""
    return (
        await session.execute(
            select(func.count())
            .select_from(Outreach)
            .join(Lead)
            .where(
                Lead.job_id == job_id,
                (Outreach.send_status == "queued") | (Outreach.wa_send_status == "queued"),
            )
        )
    ).scalar_one()


async def _table_response(request: Request, session: AsyncSession, job: Job, params: dict):
    """Render the lead table partial with everything it needs (leads, stats, queue depth)."""
    leads = await _load_leads(session, job.id, params)
    return templates.TemplateResponse(
        request,
        "partials/lead_table.html",
        {
            "job": job,
            "leads": leads,
            "params": params,
            "settings": get_settings(),
            "queued_count": await _count_queued(session, job.id),
        },
    )


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
        {
            "job": job,
            "leads": leads,
            "params": params,
            "settings": get_settings(),
            "queued_count": await _count_queued(session, job_id),
        },
    )


@router.get("/jobs/{job_id}/leads", response_class=HTMLResponse)
async def job_leads_partial(
    job_id: str, request: Request, session: AsyncSession = Depends(get_session)
):
    """HTMX partial: the lead table + live stats (used for search/filter and polling)."""
    job = await session.get(Job, job_id)
    if job is None:
        return HTMLResponse("Job not found", status_code=404)
    return await _table_response(request, session, job, dict(request.query_params))


@router.post("/jobs/{job_id}/bulk-approve", response_class=HTMLResponse)
async def job_bulk_approve(
    job_id: str,
    request: Request,
    min_score: float = Form(0.0),
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(Job, job_id)
    if job is None:
        return HTMLResponse("Job not found", status_code=404)
    await bulk_approve(session, job_id, min_score)
    return await _table_response(request, session, job, dict(request.query_params))


@router.post("/jobs/{job_id}/bulk-send", response_class=HTMLResponse)
async def job_bulk_send(
    job_id: str,
    request: Request,
    channel: str = Form("email"),
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(Job, job_id)
    if job is None:
        return HTMLResponse("Job not found", status_code=404)
    channel = "whatsapp" if channel == "whatsapp" else "email"
    await bulk_queue(session, job_id, channel)
    return await _table_response(request, session, job, dict(request.query_params))


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
    return templates.TemplateResponse(
        request, "lead_review.html", {"lead": lead, "settings": get_settings()}
    )


@router.post("/leads/{lead_id}/approve", response_class=HTMLResponse)
async def lead_approve(
    lead_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    lead = await session.get(Lead, lead_id, options=[selectinload(Lead.outreach)])
    if lead and lead.outreach:
        lead.outreach.review_status = "approved"
        await session.commit()
    return _panel(request, lead)


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
    return _panel(request, lead)


@router.post("/leads/{lead_id}/regenerate", response_class=HTMLResponse)
async def lead_regenerate(
    lead_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    lead = await session.get(Lead, lead_id, options=[selectinload(Lead.outreach)])
    if lead:
        await process_lead(session, lead)
        await session.refresh(lead, attribute_names=["outreach"])
    return _panel(request, lead)


# ------------------------------------------------------------------ sending
@router.post("/leads/{lead_id}/send", response_class=HTMLResponse)
async def lead_send_email(
    lead_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    lead = await session.get(Lead, lead_id, options=[selectinload(Lead.outreach)])
    if lead is None:
        return HTMLResponse("Lead not found", status_code=404)
    await send_email_for_lead(session, lead)
    return _panel(request, lead)


@router.post("/leads/{lead_id}/send-whatsapp", response_class=HTMLResponse)
async def lead_send_whatsapp(
    lead_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    lead = await session.get(Lead, lead_id, options=[selectinload(Lead.outreach)])
    if lead is None:
        return HTMLResponse("Lead not found", status_code=404)
    await send_whatsapp_for_lead(session, lead)
    return _panel(request, lead)


@router.post("/leads/{lead_id}/opt-in", response_class=HTMLResponse)
async def lead_toggle_opt_in(
    lead_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    lead = await session.get(Lead, lead_id, options=[selectinload(Lead.outreach)])
    if lead:
        lead.opt_in = 0 if lead.opt_in else 1
        await session.commit()
    return _panel(request, lead)


# ------------------------------------------------------------------ compliance
@router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(email: str = "", session: AsyncSession = Depends(get_session)):
    added = await suppression.add_suppression(session, email, reason="unsubscribe")
    safe = html.escape(email or "")
    note = (
        "You've been unsubscribed and won't receive further emails."
        if added
        else "This address is already unsubscribed."
        if email
        else "No email address supplied."
    )
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:system-ui;max-width:34rem;margin:4rem auto;"
        "padding:0 1rem;color:#0f172a'>"
        "<h1 style='font-size:1.25rem'>Unsubscribe</h1>"
        f"<p>{note}</p>"
        + (f"<p style='color:#64748b'>{safe}</p>" if safe else "")
        + "</body>"
    )


# ------------------------------------------------------------------ inbound webhooks
@router.post("/webhooks/email")
async def webhook_email(request: Request, session: AsyncSession = Depends(get_session)):
    """Receive delivery events from the email provider (bounce / complaint / reply).

    Tolerant of shapes: accepts a single object or a list, and looks for the address under
    ``email`` / ``to`` (or ``data.to``) and the event under ``event`` / ``type`` / ``status``.
    Hard bounces and complaints auto-suppress the address.
    """
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "invalid json"}, status_code=400)

    events = payload if isinstance(payload, list) else [payload]
    updated = 0
    for e in events:
        if not isinstance(e, dict):
            continue
        data = e.get("data") if isinstance(e.get("data"), dict) else {}
        to = e.get("email") or e.get("to") or data.get("to") or data.get("email")
        if isinstance(to, list):
            to = to[0] if to else None
        event = e.get("event") or e.get("type") or e.get("status") or ""
        if to:
            updated += await record_email_event(session, str(to), str(event))
    return {"updated": updated}


@router.post("/webhooks/whatsapp")
async def webhook_whatsapp(request: Request, session: AsyncSession = Depends(get_session)):
    """Receive WhatsApp status/inbound events (Meta Cloud API shape, or a simple test shape).

    Maps a ``failed`` delivery status to ``bounced`` and an inbound message to ``replied``.
    """
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "invalid json"}, status_code=400)

    updated = 0
    # Simple test shape: {"phone": "...", "event": "replied"}.
    if isinstance(payload, dict) and payload.get("phone"):
        updated += await record_whatsapp_event(
            session, str(payload["phone"]), str(payload.get("event", ""))
        )
        return {"updated": updated}

    # Meta Cloud API shape: entry[].changes[].value.{statuses[],messages[]}.
    for entry in (payload.get("entry") or []) if isinstance(payload, dict) else []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for st in value.get("statuses") or []:
                recipient = st.get("recipient_id") or ""
                status = st.get("status") or ""
                if recipient and status:
                    updated += await record_whatsapp_event(session, recipient, status)
            for msg in value.get("messages") or []:
                sender = msg.get("from") or ""
                if sender:
                    updated += await record_whatsapp_event(session, sender, "replied")
    return {"updated": updated}


# ------------------------------------------------------------------ export
@router.get("/jobs/{job_id}/export.csv")
async def export_job_csv(
    job_id: str, request: Request, session: AsyncSession = Depends(get_session)
):
    """Download this job's leads + generated outreach as CSV (respects current filters)."""
    job = await session.get(Job, job_id)
    if job is None:
        return HTMLResponse("Job not found", status_code=404)
    leads = await _load_leads(session, job_id, dict(request.query_params))

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "name", "position", "company", "industry", "email", "phone",
        "quality_score", "review_status", "send_status", "wa_send_status",
        "email_subject", "email_body", "whatsapp_body",
    ])
    for lead in leads:
        o = lead.outreach
        writer.writerow([
            lead.name or "", lead.position or "", lead.company or "",
            lead.industry or "", lead.email or "", lead.phone or "",
            (o.quality_score if o else "") or "",
            (o.review_status if o else ""),
            (o.send_status if o else ""),
            (o.wa_send_status if o else ""),
            (o.email_subject if o else "") or "",
            (o.email_body if o else "") or "",
            (o.whatsapp_body if o else "") or "",
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="leadforge-{job_id}.csv"'},
    )
