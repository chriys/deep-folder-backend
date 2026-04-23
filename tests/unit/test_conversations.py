from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.db import get_session
from deepfolder.main import create_app


async def _create_mock_session() -> AsyncGenerator[AsyncSession, None]:
    session = AsyncMock(spec=AsyncSession)
    yield session


@pytest.fixture
def app():
    application = create_app()
    application.dependency_overrides[get_session] = _create_mock_session
    return application


@pytest.mark.asyncio
async def test_create_conversation_requires_auth(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/conversations",
            json={"folder_id": 1},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_conversations_requires_auth(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/conversations")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_conversation_requires_auth(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/conversations/1")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delete_conversation_requires_auth(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.delete("/conversations/1")

    assert response.status_code == 401
