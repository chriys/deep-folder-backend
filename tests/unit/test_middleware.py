"""Tests for request logging middleware."""
import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from deepfolder.logging_config import configure_logging
from deepfolder.middleware import RequestLoggingMiddleware


@pytest.fixture(autouse=True)
def setup_logging() -> None:
    configure_logging()


def make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/fail")
    async def fail() -> None:
        raise RuntimeError("boom")

    return app


def test_middleware_logs_request_fields(capsys: pytest.CaptureFixture[str]) -> None:
    """Middleware emits one JSON log line per request with required fields."""
    client = TestClient(make_app(), raise_server_exceptions=False)
    client.get("/ping")

    lines = [l for l in capsys.readouterr().out.strip().splitlines() if l]
    records = [json.loads(l) for l in lines]

    # Find the request-completed log
    req_log = next(r for r in records if r.get("event") == "http.request")
    assert req_log["method"] == "GET"
    assert req_log["path"] == "/ping"
    assert req_log["status"] == 200
    assert isinstance(req_log["duration_ms"], float)
    assert "request_id" in req_log


def test_middleware_request_id_is_unique(capsys: pytest.CaptureFixture[str]) -> None:
    """Each request gets a distinct request_id."""
    client = TestClient(make_app(), raise_server_exceptions=False)
    client.get("/ping")
    client.get("/ping")

    lines = [l for l in capsys.readouterr().out.strip().splitlines() if l]
    records = [json.loads(l) for l in lines]
    req_logs = [r for r in records if r.get("event") == "http.request"]
    ids = [r["request_id"] for r in req_logs]
    assert ids[0] != ids[1]


def test_middleware_logs_non_200_status(capsys: pytest.CaptureFixture[str]) -> None:
    """Status code is captured even for error responses."""
    client = TestClient(make_app(), raise_server_exceptions=False)
    client.get("/fail")

    lines = [l for l in capsys.readouterr().out.strip().splitlines() if l]
    records = [json.loads(l) for l in lines]
    req_log = next(r for r in records if r.get("event") == "http.request")
    assert req_log["status"] == 500
