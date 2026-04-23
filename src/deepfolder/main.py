from fastapi import FastAPI

from deepfolder.api.auth import router as auth_router
from deepfolder.api.conversations import router as conversations_router
from deepfolder.api.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="Deep Folder Backend")
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(conversations_router)
    return app


app = create_app()
