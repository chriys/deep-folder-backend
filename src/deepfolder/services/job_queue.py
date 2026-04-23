from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.models.job import Job


class JobQueue:
    """Postgres-backed job queue using SKIP LOCKED for concurrency."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def enqueue(
        self, kind: str, payload: dict[str, Any], run_after: datetime | None = None
    ) -> int:
        """Enqueue a job to be processed by workers.

        Args:
            kind: Job type identifier for handler lookup
            payload: JSON-serializable job data
            run_after: If set, job won't be claimed before this time

        Returns:
            Job ID
        """
        job = Job(kind=kind, payload=payload, status="pending", attempts=0, run_after=run_after)
        self.session.add(job)
        await self.session.flush()
        assert job.id is not None
        return job.id

    async def claim(self) -> Job | None:
        """Claim a pending job for processing using SKIP LOCKED.

        Returns only jobs where run_after is None or in the past.
        Updates status to 'running' atomically.

        Returns:
            Job if one was available, None otherwise
        """
        now = datetime.now(timezone.utc)
        stmt = (
            select(Job)
            .where(
                and_(
                    Job.status == "pending",
                    (Job.run_after.is_(None)) | (Job.run_after <= now),  # type: ignore
                )
            )
            .with_for_update(skip_locked=True)
            .limit(1)
        )

        result = await self.session.execute(stmt)
        job = result.scalar_one_or_none()

        if job is not None:
            job.status = "running"
            await self.session.flush()

        return job

    async def mark_succeeded(self, job_id: int) -> None:
        """Mark a job as successfully completed."""
        job = await self.session.get(Job, job_id)
        if job is not None:
            job.status = "succeeded"
            await self.session.flush()

    async def mark_failed(self, job_id: int, error: str) -> None:
        """Mark a job as failed and record the error.

        Increments attempt counter and records error message.
        Does NOT reset status to pending — that's handled by the worker
        retry logic or a separate mechanism.
        """
        job = await self.session.get(Job, job_id)
        if job is not None:
            job.status = "failed"
            job.attempts += 1
            job.last_error = error
            await self.session.flush()
