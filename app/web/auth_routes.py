"""Public authentication routes: login form, login POST, logout, and admin user mgmt."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service as auth_service
from app.auth.deps import current_user
from app.db import get_session
from app.models import User

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    user = await auth_service.authenticate(session, email, password)
    if user is None:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid email or password."}, status_code=401
        )
    request.session["user_id"] = user.id
    request.session["user_email"] = user.email
    request.session["user_role"] = user.role
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ---------------------------------------------------------------- admin: user management
@router.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if not user or user.role != "admin":
        return HTMLResponse("Admins only", status_code=403)
    users = (await session.execute(select(User).order_by(User.id))).scalars().all()
    return templates.TemplateResponse(request, "users.html", {"users": users, "me": user})


@router.post("/users", response_class=HTMLResponse)
async def users_create(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("member"),
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if not user or user.role != "admin":
        return HTMLResponse("Admins only", status_code=403)
    if not await auth_service.get_user_by_email(session, email):
        await auth_service.create_user(
            session, email=email, password=password,
            role="admin" if role == "admin" else "member",
        )
    return RedirectResponse("/users", status_code=303)
