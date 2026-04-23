from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

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
async def test_create_folder_requires_auth(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/folders",
            json={"drive_url": "https://drive.google.com/drive/folders/12345"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_folders_requires_auth(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/folders")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_folder_requires_auth(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/folders/1")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delete_folder_requires_auth(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.delete("/folders/1")

    assert response.status_code == 401
