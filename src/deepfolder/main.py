"""FastAPI application factory."""
from __future__ import annotations

from fastapi import FastAPI

from deepfolder.config import settings
from deepfolder.logging_config import configure_logging
from deepfolder.middleware import RequestLoggingMiddleware
from deepfolder.sentry import init_sentry


def create_app() -> FastAPI:
    configure_logging()
    init_sentry(dsn=settings.sentry_dsn)

    app = FastAPI(title="Deep Folder Backend")
    app.add_middleware(RequestLoggingMiddleware)

    from deepfolder.api.health import router as health_router

    app.include_router(health_router)

    return app


app = create_app()
