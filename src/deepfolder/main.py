"""FastAPI application factory."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from deepfolder.config import settings
from deepfolder.logging_config import configure_logging
from deepfolder.middleware import RequestLoggingMiddleware
from deepfolder.sentry import init_sentry
from deepfolder.api.auth import router as auth_router
from deepfolder.api.conversations import router as conversations_router
from deepfolder.api.folders import router as folders_router
from deepfolder.api.health import router as health_router
from deepfolder.api.usage import router as usage_router


def create_app() -> FastAPI:
    configure_logging()
    init_sentry(dsn=settings.sentry_dsn)

    app = FastAPI(title="Deep Folder Backend")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(conversations_router)
    app.include_router(folders_router)
    app.include_router(usage_router)
    return app


app = create_app()
