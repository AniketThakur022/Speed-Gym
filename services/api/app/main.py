"""VMSG FastAPI application — app factory + lifespan.

Router surface mirrors the pre-loss Sprint-0 build (health/content/practice);
the /api/v1 consumer contract (auth, dashboard, sync) lands with Sprint 1 —
see memory `api-contract-v1` for the frozen resolution.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from . import db
from .routers import auth, content, health, internal, practice, session, sync, webhooks


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await db.close_all()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Device-Fingerprint"],
    )
    app.include_router(health.router)
    app.include_router(auth.router, prefix=settings.api_v1_prefix)
    app.include_router(session.router, prefix=settings.api_v1_prefix)
    app.include_router(sync.router, prefix=settings.api_v1_prefix)
    app.include_router(webhooks.router)
    app.include_router(internal.router)
    app.include_router(content.router)
    app.include_router(practice.router)
    return app


app = create_app()
