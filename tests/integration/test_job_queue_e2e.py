"""End-to-end test for job queue with real database."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.db import Base, _get_engine, _get_session_factory
from deepfolder.models.job import Job
from deepfolder.services.job_queue import JobQueue


@pytest.mark.asyncio
async def test_job_queue_roundtrip():
    """Test complete job lifecycle: enqueue, claim, succeed."""
    # Note: This test requires DATABASE_URL to be set and a real database to be available
    engine = _get_engine()

    # Create tables (in real use, Alembic migrations handle this)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = _get_session_factory()

    async with async_session_factory() as session:
        queue = JobQueue(session)

        # Enqueue a job
        job_id = await queue.enqueue(kind="noop", payload={"test": "data"})
        await session.commit()

        assert job_id is not None

    # In a new session, claim the job
    async with async_session_factory() as session:
        queue = JobQueue(session)
        claimed_job = await queue.claim()
        await session.commit()

        assert claimed_job is not None
        assert claimed_job.kind == "noop"
        assert claimed_job.payload == {"test": "data"}
        assert claimed_job.status == "running"

        claimed_id = claimed_job.id

    # Mark as succeeded
    async with async_session_factory() as session:
        queue = JobQueue(session)
        await queue.mark_succeeded(claimed_id)
        await session.commit()

    # Verify final state
    async with async_session_factory() as session:
        job = await session.get(Job, claimed_id)
        assert job.status == "succeeded"

    # Clean up
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.mark.asyncio
async def test_run_after_gating():
    """Test that run_after gates job claiming."""
    engine = _get_engine()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = _get_session_factory()

    async with async_session_factory() as session:
        queue = JobQueue(session)

        # Enqueue a job that should run in the future
        future_time = datetime.now(timezone.utc) + timedelta(hours=1)
        await queue.enqueue(kind="noop", payload={}, run_after=future_time)

        # Try to claim - should get None
        claimed_job = await queue.claim()
        assert claimed_job is None

        # Enqueue a job with no run_after (should be claimable immediately)
        await queue.enqueue(kind="noop", payload={})

        # Now claim should work
        claimed_job = await queue.claim()
        assert claimed_job is not None
        assert claimed_job.status == "running"

        await session.commit()

    # Clean up
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()
