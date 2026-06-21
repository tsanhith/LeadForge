"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.auth.deps import AuthMiddleware
from app.auth.service import seed_admin
from app.config import get_settings
from app.db import init_db
from app.pipeline.queue import recover_pending_jobs
from app.pipeline.worker import start_worker
from app.send_worker import start_send_worker
from app.sequence_worker import start_sequence_worker
from app.web.auth_routes import router as auth_router
from app.web.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await init_db()
    await seed_admin()
    # The in-process worker only runs for the inprocess backend; arq runs separately.
    if settings.queue_backend != "arq":
        start_worker()
    start_send_worker()
    start_sequence_worker()
    await recover_pending_jobs()  # resume jobs interrupted by a restart
    yield


app = FastAPI(title="LeadForge", lifespan=lifespan)

# Middleware order: SessionMiddleware must wrap (run before) AuthMiddleware so the session is
# populated when the gate checks it. The last-added middleware is outermost.
app.add_middleware(AuthMiddleware)
app.add_middleware(SessionMiddleware, secret_key=get_settings().session_secret)

app.include_router(auth_router)
app.include_router(router)
