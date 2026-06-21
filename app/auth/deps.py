"""Auth dependencies + the request-gating middleware.

The middleware enforces "must be signed in" for the whole app, with a small allowlist of
public paths (login, the unsubscribe page, provider webhooks, health). It only checks for a
session — routes that need the actual :class:`User` use the ``current_user`` dependency.
"""
from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.db import get_session
from app.models import User

# Paths reachable without signing in. Webhooks authenticate with a shared secret instead.
_PUBLIC_PREFIXES = ("/login", "/logout", "/unsubscribe", "/webhooks", "/health", "/static", "/favicon")


def _is_public(path: str) -> bool:
    return any(path == p or path.startswith(p) for p in _PUBLIC_PREFIXES)


class AuthMiddleware(BaseHTTPMiddleware):
    """Redirect unauthenticated requests to /login (HX-Redirect for HTMX calls)."""

    async def dispatch(self, request: Request, call_next):
        if _is_public(request.url.path) or request.session.get("user_id"):
            return await call_next(request)
        if request.headers.get("HX-Request"):
            resp = Response(status_code=204)
            resp.headers["HX-Redirect"] = "/login"
            return resp
        return RedirectResponse("/login", status_code=303)


async def current_user(
    request: Request, session=Depends(get_session)
) -> User | None:
    uid = request.session.get("user_id")
    if not uid:
        return None
    return await session.get(User, uid)


async def require_admin(user: User | None = Depends(current_user)) -> User | None:
    # The middleware already guarantees a session; this narrows to admins for admin pages.
    return user if (user and user.role == "admin") else None
