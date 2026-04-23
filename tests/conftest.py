from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from deepfolder.db import Base


@pytest.fixture
async def postgres_db(postgresql):
    """Set up PostgreSQL database for tests.

    Uses pytest-postgresql to provide a real PostgreSQL database instance.
    Creates all tables before yielding and drops them after the test.
    """
    database_url = f"postgresql+asyncpg://{postgresql.info.user}:{postgresql.info.password}@{postgresql.info.host}:{postgresql.info.port}/{postgresql.info.dbname}"

    engine = create_async_engine(database_url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield database_url

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def async_session(postgres_db) -> AsyncGenerator[AsyncSession, None]:
    """Provide an async SQLAlchemy session for tests.

    Session is automatically rolled back after each test to ensure isolation.
    """
    engine = create_async_engine(postgres_db, echo=False)
    async_session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_factory() as session:
        yield session
        await session.rollback()

    await engine.dispose()
