import json
from datetime import datetime, timezone, timedelta
from typing import Any, Callable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.models.folder import Folder
from deepfolder.models.job import Job


class JobQueue:
    @staticmethod
    async def dequeue_job(session: AsyncSession) -> Job | None:
        """Get the next pending job that's ready to run."""
        result = await session.execute(
            select(Job)
            .where(
                (Job.status == "pending")
                & (Job.run_after <= datetime.now(timezone.utc))
            )
            .order_by(Job.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def mark_in_progress(session: AsyncSession, job_id: int) -> None:
        """Mark a job as in progress."""
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(status="in_progress")
        )
        await session.commit()

    @staticmethod
    async def mark_complete(session: AsyncSession, job_id: int) -> None:
        """Mark a job as complete."""
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(status="complete", updated_at=datetime.now(timezone.utc))
        )
        await session.commit()

    @staticmethod
    async def mark_failed(
        session: AsyncSession, job_id: int, error: str, retry_after_seconds: int = 300
    ) -> None:
        """Mark a job as failed and schedule retry."""
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status="pending",
                last_error=error,
                attempts=Job.attempts + 1,
                run_after=datetime.now(timezone.utc) + timedelta(seconds=retry_after_seconds),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()


class JobHandlers:
    _handlers: dict[str, Callable[[AsyncSession, Job], Any]] = {}

    @classmethod
    def register(cls, job_type: str) -> Callable:
        """Decorator to register a job handler."""
        def decorator(func: Callable) -> Callable:
            cls._handlers[job_type] = func
            return func
        return decorator

    @classmethod
    async def execute(cls, session: AsyncSession, job: Job) -> None:
        """Execute a job by its type."""
        handler = cls._handlers.get(job.job_type)
        if not handler:
            raise ValueError(f"No handler registered for job type: {job.job_type}")
        await handler(session, job)


@JobHandlers.register("ingest_folder")
async def handle_ingest_folder(session: AsyncSession, job: Job) -> None:
    """Stub handler for ingest_folder job."""
    payload = json.loads(job.payload)
    folder_id = payload["folder_id"]

    result = await session.execute(
        select(Folder).where(Folder.id == folder_id)
    )
    folder = result.scalar_one_or_none()
    if folder:
        folder.state = "ready"
        folder.file_count = 0
        await session.commit()
