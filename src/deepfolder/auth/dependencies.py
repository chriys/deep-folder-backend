from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.auth.session import SessionManager
from deepfolder.config import settings
from deepfolder.db import get_session
from deepfolder.models.user import User

_session_manager = SessionManager(settings.secret_key)


async def require_user(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> User:
    email = _session_manager.get_email(request)
    if not email:
        raise HTTPException(status_code=401, detail="Not authenticated")
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
