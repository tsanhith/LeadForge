"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import init_db
from app.pipeline.worker import start_worker
from app.web.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_worker()
    yield


app = FastAPI(title="LeadForge", lifespan=lifespan)
app.include_router(router)
