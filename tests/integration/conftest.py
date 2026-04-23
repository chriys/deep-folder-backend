"""Integration test fixtures.

Extends the root conftest with pgvector support for end-to-end tests.
"""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from deepfolder.db import Base


@pytest.fixture(scope="session")
def integration_enabled() -> bool:
    """Gate: only run integration tests when INTEGRATION_TEST=1."""
    import os
    return os.environ.get("INTEGRATION_TEST") == "1"


@pytest.fixture
async def postgres_db_vector(postgresql):
    """Set up PostgreSQL with pgvector extension for integration tests.

    Creates the vector extension before tables, then creates all tables.
    The embedding column in the ORM model uses ARRAY(float) which maps to
    float[] in Postgres; we alter it to vector(1024) for the pgvector <-> operator.
    """
    database_url = (
        f"postgresql+asyncpg://{postgresql.info.user}:{postgresql.info.password}"
        f"@{postgresql.info.host}:{postgresql.info.port}/{postgresql.info.dbname}"
    )
    engine = create_async_engine(database_url, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        # Alter embedding column from float[] to vector(1024) for pgvector ops
        await conn.execute(
            text(
                "ALTER TABLE chunks "
                "ALTER COLUMN embedding TYPE vector(1024) "
                "USING embedding::vector"
            )
        )
    yield database_url
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def async_session(postgres_db_vector) -> AsyncGenerator[AsyncSession, None]:
    """Provide an async SQLAlchemy session backed by pgvector-enabled DB."""
    engine = create_async_engine(postgres_db_vector, echo=False)
    async_session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()
