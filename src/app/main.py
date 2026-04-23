from fastapi import FastAPI
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


app = FastAPI(title="Deep Folder Backend")


@app.get("/health", response_model=HealthResponse)
async def health():
    return {"status": "ok"}
