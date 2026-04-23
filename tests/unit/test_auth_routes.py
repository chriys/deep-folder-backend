from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.db import get_session
from deepfolder.main import create_app
from deepfolder.models.user import User


async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
    session = AsyncMock(spec=AsyncSession)
    yield session


@pytest.fixture
def app():  # type: ignore[no-untyped-def]
    application = create_app()
    application.dependency_overrides[get_session] = _override_get_session
    return application


@pytest.mark.asyncio
async def test_auth_start_redirects_to_google(app) -> None:  # type: ignore[no-untyped-def]
    mock_flow = MagicMock()
    mock_flow.authorization_url.return_value = (
        "https://accounts.google.com/o/oauth2/auth?scope=drive.readonly",
        "state123",
    )

    with patch("deepfolder.api.auth.flow_from_client_config", return_value=mock_flow):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/auth/google/start", follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    assert "accounts.google.com" in location
    assert "drive.readonly" in location


@pytest.mark.asyncio
async def test_auth_callback_rejects_disallowed_email(app) -> None:  # type: ignore[no-untyped-def]
    mock_credentials = MagicMock()
    mock_credentials.token = "access_token"
    mock_credentials.refresh_token = "refresh_token"

    mock_flow = MagicMock()
    mock_flow.fetch_token = MagicMock()
    mock_flow.credentials = mock_credentials

    with (
        patch("deepfolder.api.auth.flow_from_client_config", return_value=mock_flow),
        patch(
            "deepfolder.api.auth._get_user_email",
            new=AsyncMock(return_value="notallowed@example.com"),
        ),
        patch("deepfolder.api.auth.settings") as mock_settings,
    ):
        mock_settings.allowed_emails = ["allowed@example.com"]
        mock_settings.secret_key = "supersecretkey1234567890123456789012345678"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/auth/google/callback?code=test_code")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_auth_callback_allowed_email_sets_cookie(app) -> None:  # type: ignore[no-untyped-def]
    mock_credentials = MagicMock()
    mock_credentials.token = "access_token"
    mock_credentials.refresh_token = "ya29.refresh_token"

    mock_flow = MagicMock()
    mock_flow.fetch_token = MagicMock()
    mock_flow.credentials = mock_credentials

    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def _session_with_user() -> AsyncGenerator[AsyncSession, None]:
        yield mock_session

    app.dependency_overrides[get_session] = _session_with_user

    with (
        patch("deepfolder.api.auth.flow_from_client_config", return_value=mock_flow),
        patch(
            "deepfolder.api.auth._get_user_email",
            new=AsyncMock(return_value="allowed@example.com"),
        ),
        patch("deepfolder.api.auth.settings") as mock_settings,
    ):
        mock_settings.allowed_emails = ["allowed@example.com"]
        mock_settings.secret_key = "supersecretkey1234567890123456789012345678"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/auth/google/callback?code=test_code", follow_redirects=False
            )

    assert response.status_code == 302
    assert "session" in response.cookies


@pytest.mark.asyncio
async def test_auth_status_unauthenticated_returns_401(app) -> None:  # type: ignore[no-untyped-def]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/auth/status")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_disconnect_unauthenticated_returns_401(app) -> None:  # type: ignore[no-untyped-def]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/auth/disconnect")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_status_with_valid_session(app) -> None:  # type: ignore[no-untyped-def]
    from deepfolder.auth.dependencies import require_user

    mock_user = User(email="allowed@example.com", encrypted_refresh_token="encrypted")
    app.dependency_overrides[require_user] = lambda: mock_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/auth/status")

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "allowed@example.com"
    assert data["drive_connected"] is True
