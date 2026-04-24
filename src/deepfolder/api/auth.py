import base64
import hashlib
import os
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from google_auth_oauthlib.flow import Flow  # type: ignore[import-untyped]
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.auth.dependencies import require_user
from deepfolder.auth.session import SessionManager
from deepfolder.auth.token_vault import TokenVault
from deepfolder.config import settings
from deepfolder.db import get_session
from deepfolder.models.user import User

router = APIRouter(prefix="/auth")

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.activity.readonly",
]
GOOGLE_TOKEN_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
PKCE_COOKIE_NAME = "pkce_verifier"
PKCE_MAX_AGE = 300  # 5 minutes


def _generate_pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _pkce_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="pkce")


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
    verifier, challenge = _generate_pkce_pair()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    signed = _pkce_serializer().dumps(verifier)
    response = RedirectResponse(url=auth_url, status_code=302)
    response.set_cookie(
        PKCE_COOKIE_NAME,
        signed,
        max_age=PKCE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=True,
    )
    return response


@router.get("/google/callback")
async def auth_callback(
    request: Request,
    code: str,
    db: AsyncSession = Depends(get_session),
) -> Response:
    signed_verifier = request.cookies.get(PKCE_COOKIE_NAME)
    if not signed_verifier:
        raise HTTPException(status_code=400, detail="Missing PKCE cookie")
    try:
        verifier: str = _pkce_serializer().loads(signed_verifier, max_age=PKCE_MAX_AGE)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status_code=400, detail="Invalid or expired PKCE cookie")

    flow = flow_from_client_config()
    flow.fetch_token(code=code, code_verifier=verifier)
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
    response.delete_cookie(PKCE_COOKIE_NAME)
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
