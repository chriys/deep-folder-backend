from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from deepfolder.config import settings


class Base(DeclarativeBase):
    pass


_engine: Any = None
_async_session_factory: Any = None


def _get_engine() -> Any:
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.database_url, echo=settings.debug)
    return _engine


def _get_session_factory() -> Any:
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(_get_engine(), expire_on_commit=False)
    return _async_session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with _get_session_factory()() as session:
        yield session
