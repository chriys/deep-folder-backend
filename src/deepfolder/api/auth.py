from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from google_auth_oauthlib.flow import Flow  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.auth.dependencies import require_user
from deepfolder.auth.session import SessionManager
from deepfolder.auth.token_vault import TokenVault
from deepfolder.config import settings
from deepfolder.db import get_session
from deepfolder.models.user import User

router = APIRouter(prefix="/auth")

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
GOOGLE_TOKEN_REVOKE_URL = "https://oauth2.googleapis.com/revoke"


def _client_config() -> dict[str, Any]:
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }


def flow_from_client_config() -> Flow:
    return Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        redirect_uri=settings.google_redirect_uri,
    )


async def _get_user_email(token: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        email: str = data["email"]
        return email


@router.get("/google/start")
async def auth_start() -> RedirectResponse:
    flow = flow_from_client_config()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/google/callback")
async def auth_callback(
    request: Request,
    code: str,
    db: AsyncSession = Depends(get_session),
) -> Response:
    flow = flow_from_client_config()
    flow.fetch_token(code=code)
    credentials = flow.credentials

    email = await _get_user_email(credentials.token)

    if settings.allowed_emails and email not in settings.allowed_emails:
        raise HTTPException(status_code=403, detail="Email not in allowlist")

    vault = TokenVault(settings.secret_key)
    encrypted_token = vault.encrypt(credentials.refresh_token) if credentials.refresh_token else None

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(email=email, encrypted_refresh_token=encrypted_token)
        db.add(user)
    else:
        user.encrypted_refresh_token = encrypted_token
    await db.commit()

    session_mgr = SessionManager(settings.secret_key)
    response = RedirectResponse(url="/", status_code=302)
    session_mgr.set_session(response, email)
    return response


@router.get("/status")
async def auth_status(user: User = Depends(require_user)) -> dict[str, Any]:
    has_token = user.encrypted_refresh_token is not None
    return {"email": user.email, "drive_connected": has_token}


@router.post("/disconnect")
async def auth_disconnect(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_session),
) -> Response:
    if user.encrypted_refresh_token:
        vault = TokenVault(settings.secret_key)
        try:
            refresh_token = vault.decrypt(user.encrypted_refresh_token)
            async with httpx.AsyncClient() as client:
                await client.post(
                    GOOGLE_TOKEN_REVOKE_URL,
                    params={"token": refresh_token},
                )
        except Exception:
            pass

    user.encrypted_refresh_token = None
    await db.commit()

    session_mgr = SessionManager(settings.secret_key)
    response = JSONResponse({"status": "disconnected"})
    session_mgr.clear_session(response)
    return response
