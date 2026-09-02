"""VMSG FastAPI application — app factory + lifespan.

Router surface mirrors the pre-loss Sprint-0 build (health/content/practice);
the /api/v1 consumer contract (auth, dashboard, sync) lands with Sprint 1 —
see memory `api-contract-v1` for the frozen resolution.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from . import db
from .routers import content, health, practice


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await db.close_all()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(content.router)
    app.include_router(practice.router)
    return app


app = create_app()
