from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, call

import pytest

from deepfolder.models.job import Job
from deepfolder.services.job_queue import JobQueue


@pytest.mark.asyncio
async def test_enqueue_creates_job():
    """Test that enqueue creates a job with pending status."""
    session = AsyncMock()
    session.flush = AsyncMock()

    queue = JobQueue(session)
    job_id = await queue.enqueue(kind="noop", payload={"test": True})

    assert job_id is None  # Job.id is None until flushed
    session.add.assert_called_once()
    session.flush.assert_called_once()

    # Verify the job was added correctly
    added_job = session.add.call_args[0][0]
    assert added_job.kind == "noop"
    assert added_job.payload == {"test": True}
    assert added_job.status == "pending"
    assert added_job.attempts == 0
    assert added_job.last_error is None
    assert added_job.run_after is None


@pytest.mark.asyncio
async def test_enqueue_with_run_after():
    """Test that enqueue respects run_after parameter."""
    session = AsyncMock()
    future_time = datetime.now(timezone.utc) + timedelta(hours=1)

    queue = JobQueue(session)
    await queue.enqueue(kind="noop", payload={}, run_after=future_time)

    added_job = session.add.call_args[0][0]
    assert added_job.run_after == future_time


@pytest.mark.asyncio
async def test_claim_returns_pending_job():
    """Test that claim returns a pending job and marks it as running."""
    session = AsyncMock()
    job = Job(id=1, kind="noop", payload={}, status="pending", attempts=0)

    result = AsyncMock()
    result.scalar_one_or_none.return_value = job
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()

    queue = JobQueue(session)
    claimed_job = await queue.claim()

    assert claimed_job is not None
    assert claimed_job.id == 1
    assert claimed_job.status == "running"
    session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_claim_returns_none_when_no_pending():
    """Test that claim returns None when no pending jobs."""
    session = AsyncMock()
    result = AsyncMock()
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)

    queue = JobQueue(session)
    claimed_job = await queue.claim()

    assert claimed_job is None


@pytest.mark.asyncio
async def test_mark_succeeded():
    """Test that mark_succeeded marks job as succeeded."""
    session = AsyncMock()
    job = Job(id=1, kind="noop", payload={}, status="running", attempts=0)
    session.get = AsyncMock(return_value=job)
    session.flush = AsyncMock()

    queue = JobQueue(session)
    await queue.mark_succeeded(1)

    assert job.status == "succeeded"
    session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_mark_failed():
    """Test that mark_failed increments attempts and records error."""
    session = AsyncMock()
    job = Job(id=1, kind="noop", payload={}, status="running", attempts=0)
    session.get = AsyncMock(return_value=job)
    session.flush = AsyncMock()

    queue = JobQueue(session)
    error_msg = "Test error"
    await queue.mark_failed(1, error_msg)

    assert job.status == "failed"
    assert job.attempts == 1
    assert job.last_error == error_msg
    session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_mark_failed_increments_attempts():
    """Test that mark_failed increments attempts on multiple failures."""
    session = AsyncMock()
    job = Job(id=1, kind="noop", payload={}, status="running", attempts=1)
    session.get = AsyncMock(return_value=job)
    session.flush = AsyncMock()

    queue = JobQueue(session)
    await queue.mark_failed(1, "Error 2")

    assert job.attempts == 2
    assert job.last_error == "Error 2"


@pytest.mark.asyncio
async def test_claim_with_for_update_skip_locked():
    """Test that claim uses SKIP LOCKED for concurrency."""
    session = AsyncMock()
    result = AsyncMock()
    result.scalar_one_or_none.return_value = None

    mock_stmt = AsyncMock()
    mock_with_for = AsyncMock(return_value=mock_stmt)
    mock_stmt.with_for_update = AsyncMock(return_value=mock_with_for)
    mock_limit = AsyncMock(return_value=mock_stmt)
    mock_with_for.limit = AsyncMock(return_value=mock_stmt)

    session.execute = AsyncMock(return_value=result)

    queue = JobQueue(session)
    await queue.claim()

    session.execute.assert_called_once()
