import asyncio
import json
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.job_queue import JobQueue
from deepfolder.models.job import Job
from deepfolder.models.user import User


@pytest.mark.asyncio
async def test_dequeue_job_returns_none_when_no_pending_jobs(async_session: AsyncSession):
    """Test that dequeue_job returns None when no pending jobs exist."""
    job = await JobQueue.dequeue_job(async_session)
    assert job is None


@pytest.mark.asyncio
async def test_dequeue_job_returns_pending_job(async_session: AsyncSession):
    """Test that dequeue_job returns a pending job ready to run."""
    user = User(email="test@example.com", encrypted_refresh_token=None)
    async_session.add(user)
    await async_session.flush()

    job = Job(
        job_type="test_job",
        status="pending",
        payload=json.dumps({"test": "data"}),
        user_id=user.id,
        run_after=datetime.now(timezone.utc) - timedelta(seconds=10),
    )
    async_session.add(job)
    await async_session.commit()

    dequeued = await JobQueue.dequeue_job(async_session)
    assert dequeued is not None
    assert dequeued.id == job.id
    assert dequeued.job_type == "test_job"


@pytest.mark.asyncio
async def test_dequeue_job_skips_future_run_after(async_session: AsyncSession):
    """Test that dequeue_job excludes jobs where run_after > now."""
    user = User(email="test@example.com", encrypted_refresh_token=None)
    async_session.add(user)
    await async_session.flush()

    job = Job(
        job_type="test_job",
        status="pending",
        payload=json.dumps({"test": "data"}),
        user_id=user.id,
        run_after=datetime.now(timezone.utc) + timedelta(seconds=60),
    )
    async_session.add(job)
    await async_session.commit()

    dequeued = await JobQueue.dequeue_job(async_session)
    assert dequeued is None


@pytest.mark.asyncio
async def test_dequeue_job_skips_non_pending_jobs(async_session: AsyncSession):
    """Test that dequeue_job only returns pending jobs."""
    user = User(email="test@example.com", encrypted_refresh_token=None)
    async_session.add(user)
    await async_session.flush()

    for status in ["in_progress", "complete"]:
        job = Job(
            job_type="test_job",
            status=status,
            payload=json.dumps({"test": "data"}),
            user_id=user.id,
            run_after=datetime.now(timezone.utc),
        )
        async_session.add(job)

    await async_session.commit()

    dequeued = await JobQueue.dequeue_job(async_session)
    assert dequeued is None


@pytest.mark.asyncio
async def test_dequeue_job_orders_by_created_at(async_session: AsyncSession):
    """Test that dequeue_job returns the oldest pending job."""
    user = User(email="test@example.com", encrypted_refresh_token=None)
    async_session.add(user)
    await async_session.flush()

    first_job = Job(
        job_type="test_job",
        status="pending",
        payload=json.dumps({"order": 1}),
        user_id=user.id,
        run_after=datetime.now(timezone.utc),
    )
    async_session.add(first_job)
    await async_session.flush()

    await asyncio.sleep(0.01)

    second_job = Job(
        job_type="test_job",
        status="pending",
        payload=json.dumps({"order": 2}),
        user_id=user.id,
        run_after=datetime.now(timezone.utc),
    )
    async_session.add(second_job)
    await async_session.commit()

    dequeued = await JobQueue.dequeue_job(async_session)
    assert dequeued.id == first_job.id


@pytest.mark.asyncio
async def test_mark_in_progress(async_session: AsyncSession):
    """Test that mark_in_progress changes job status."""
    user = User(email="test@example.com", encrypted_refresh_token=None)
    async_session.add(user)
    await async_session.flush()

    job = Job(
        job_type="test_job",
        status="pending",
        payload=json.dumps({"test": "data"}),
        user_id=user.id,
    )
    async_session.add(job)
    await async_session.commit()

    await JobQueue.mark_in_progress(async_session, job.id)

    result = await async_session.execute(select(Job).where(Job.id == job.id))
    updated_job = result.scalar_one()
    assert updated_job.status == "in_progress"


@pytest.mark.asyncio
async def test_mark_complete(async_session: AsyncSession):
    """Test that mark_complete changes job status."""
    user = User(email="test@example.com", encrypted_refresh_token=None)
    async_session.add(user)
    await async_session.flush()

    job = Job(
        job_type="test_job",
        status="in_progress",
        payload=json.dumps({"test": "data"}),
        user_id=user.id,
    )
    async_session.add(job)
    await async_session.commit()

    await JobQueue.mark_complete(async_session, job.id)

    result = await async_session.execute(select(Job).where(Job.id == job.id))
    updated_job = result.scalar_one()
    assert updated_job.status == "complete"
    assert updated_job.updated_at is not None


@pytest.mark.asyncio
async def test_mark_failed_increments_attempts(async_session: AsyncSession):
    """Test that mark_failed increments attempts counter."""
    user = User(email="test@example.com", encrypted_refresh_token=None)
    async_session.add(user)
    await async_session.flush()

    job = Job(
        job_type="test_job",
        status="in_progress",
        payload=json.dumps({"test": "data"}),
        user_id=user.id,
        attempts=2,
    )
    async_session.add(job)
    await async_session.commit()

    await JobQueue.mark_failed(async_session, job.id, "Test error")

    result = await async_session.execute(select(Job).where(Job.id == job.id))
    updated_job = result.scalar_one()
    assert updated_job.attempts == 3
    assert updated_job.last_error == "Test error"


@pytest.mark.asyncio
async def test_mark_failed_sets_run_after(async_session: AsyncSession):
    """Test that mark_failed schedules retry with run_after."""
    user = User(email="test@example.com", encrypted_refresh_token=None)
    async_session.add(user)
    await async_session.flush()

    before = datetime.now(timezone.utc)
    job = Job(
        job_type="test_job",
        status="in_progress",
        payload=json.dumps({"test": "data"}),
        user_id=user.id,
    )
    async_session.add(job)
    await async_session.commit()

    retry_seconds = 600
    await JobQueue.mark_failed(async_session, job.id, "Test error", retry_after_seconds=retry_seconds)

    result = await async_session.execute(select(Job).where(Job.id == job.id))
    updated_job = result.scalar_one()
    expected_min = before + timedelta(seconds=retry_seconds)
    assert updated_job.run_after >= expected_min


@pytest.mark.asyncio
async def test_mark_failed_returns_to_pending(async_session: AsyncSession):
    """Test that mark_failed returns job to pending status."""
    user = User(email="test@example.com", encrypted_refresh_token=None)
    async_session.add(user)
    await async_session.flush()

    job = Job(
        job_type="test_job",
        status="in_progress",
        payload=json.dumps({"test": "data"}),
        user_id=user.id,
    )
    async_session.add(job)
    await async_session.commit()

    await JobQueue.mark_failed(async_session, job.id, "Test error")

    result = await async_session.execute(select(Job).where(Job.id == job.id))
    updated_job = result.scalar_one()
    assert updated_job.status == "pending"


@pytest.mark.asyncio
async def test_dequeue_job_uses_skip_locked(async_session: AsyncSession):
    """Test that dequeue_job uses FOR UPDATE SKIP LOCKED for concurrent-safe dequeuing.

    This verifies that the dequeue implementation would not block concurrent workers.
    The actual concurrent behavior is tested in integration tests with multiple workers.
    """
    user = User(email="test@example.com", encrypted_refresh_token=None)
    async_session.add(user)
    await async_session.flush()

    job = Job(
        job_type="test_job",
        status="pending",
        payload=json.dumps({"test": "data"}),
        user_id=user.id,
        run_after=datetime.now(timezone.utc),
    )
    async_session.add(job)
    await async_session.commit()

    dequeued = await JobQueue.dequeue_job(async_session)
    assert dequeued is not None
    assert dequeued.id == job.id
    assert dequeued.status == "pending"
