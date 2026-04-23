from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.auth.dependencies import require_user
from deepfolder.db import get_session
from deepfolder.main import create_app
from deepfolder.models.user import User


async def _create_mock_session() -> AsyncGenerator[AsyncSession, None]:
    session = AsyncMock(spec=AsyncSession)
    yield session


@pytest.fixture
def app():
    application = create_app()
    application.dependency_overrides[get_session] = _create_mock_session
    return application


def _override_user() -> User:
    user = MagicMock(spec=User)
    user.id = 1
    user.email = "test@example.com"
    return user


def _setup_auth(app):
    app.dependency_overrides[require_user] = _override_user


@pytest.mark.asyncio
async def test_get_usage_requires_auth(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/usage")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_usage_returns_rollups(app):
    _setup_auth(app)

    session = AsyncMock(spec=AsyncSession)
    total_result = MagicMock()
    total_result.one.return_value = (1.5, 100, 50)
    kind_result = MagicMock()
    kind_result.return_value = [
        ("llm", 1.0, 50, 40),
        ("embedding", 0.5, 50, 10),
    ]
    model_result = MagicMock()
    model_result.return_value = [
        ("deepseek-chat", 1.0, 50, 40),
        ("voyage-4", 0.5, 50, 10),
    ]

    execute_call_count = 0

    async def mock_execute(query, **kwargs):
        nonlocal execute_call_count
        execute_call_count += 1
        if execute_call_count == 1:
            # Total query
            return total_result
        elif execute_call_count == 2:
            # Kind query
            res = MagicMock()
            res.__iter__.return_value = iter([("llm", 1.0, 50, 40), ("embedding", 0.5, 50, 10)])
            return res
        else:
            # Model query
            res = MagicMock()
            res.__iter__.return_value = iter([("deepseek-chat", 1.0, 50, 40), ("voyage-4", 0.5, 50, 10)])
            return res

    session.execute = AsyncMock(side_effect=mock_execute)

    async def _get_session():
        yield session

    app.dependency_overrides[get_session] = _get_session

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/usage?from=2026-01-01&to=2026-04-23"
        )

    assert response.status_code == 200
    data = response.json()
    assert data["total_cost_usd"] == 1.5
    assert data["total_input_tokens"] == 100
    assert data["total_output_tokens"] == 50
    assert "llm" in data["by_kind"]
    assert "deepseek-chat" in data["by_model"]


@pytest.mark.asyncio
async def test_get_usage_invalid_date_format(app):
    _setup_auth(app)

    session = AsyncMock(spec=AsyncSession)

    async def _get_session():
        yield session

    app.dependency_overrides[get_session] = _get_session

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/usage?from=invalid-date"
        )

    assert response.status_code == 400
