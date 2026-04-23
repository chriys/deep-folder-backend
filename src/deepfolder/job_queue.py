import json
from datetime import datetime, timezone, timedelta
from typing import Any, Callable

from google.oauth2.credentials import Credentials
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.auth.token_vault import TokenVault
from deepfolder.config import settings
from deepfolder.drive_client import DriveClient
from deepfolder.models.folder import Folder
from deepfolder.models.file import File
from deepfolder.models.skipped_file import SkippedFile
from deepfolder.models.job import Job
from deepfolder.models.user import User


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
    """Ingest a Drive folder: list files, classify them, persist to database."""
    payload = json.loads(job.payload)
    folder_id = payload["folder_id"]

    result = await session.execute(select(Folder).where(Folder.id == folder_id))
    folder = result.scalar_one_or_none()
    if not folder:
        raise ValueError(f"Folder {folder_id} not found")

    user_result = await session.execute(select(User).where(User.id == folder.user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.encrypted_refresh_token:
        raise ValueError(f"User credentials not found for folder {folder_id}")

    try:
        folder.state = "ingesting"
        await session.commit()

        vault = TokenVault(settings.secret_key)
        refresh_token = vault.decrypt(user.encrypted_refresh_token)
        credentials = Credentials(token=None, refresh_token=refresh_token)

        client = DriveClient()
        files = await client.list_folder_recursive(
            folder.drive_folder_id, credentials, max_depth=5, max_files=500
        )

        file_count = 0
        for file_item in files:
            mime_type = file_item.get("mimeType", "application/octet-stream")
            file_id = file_item["id"]

            reason = _get_skip_reason(mime_type)
            if reason:
                skipped = SkippedFile(
                    folder_id=folder.id,
                    drive_file_id=file_id,
                    name=file_item["name"],
                    mime_type=mime_type,
                    reason=reason,
                )
                session.add(skipped)
            else:
                modified_time = datetime.fromisoformat(
                    file_item["modifiedTime"].replace("Z", "+00:00")
                )
                file_obj = File(
                    folder_id=folder.id,
                    drive_file_id=file_id,
                    name=file_item["name"],
                    mime_type=mime_type,
                    modified_time=modified_time,
                    extracted_at=None,
                )
                session.add(file_obj)
                file_count += 1

        folder.state = "ready"
        folder.file_count = file_count
        await session.commit()

    except Exception as e:
        folder.state = "failed"
        folder.file_count = 0
        await session.commit()
        raise


def _get_skip_reason(mime_type: str) -> str | None:
    """Determine if a file should be skipped and return the reason."""
    if mime_type.startswith("image/"):
        return "Image files not supported in v0.1"
    if mime_type.startswith("audio/"):
        return "Audio files not supported in v0.1"
    if mime_type.startswith("video/"):
        return "Video files not supported in v0.1"
    if mime_type.startswith("application/x-") or mime_type.endswith("-compressed"):
        return "Binary/archive files not supported in v0.1"

    unsupported_types = {
        "application/vnd.google-apps.presentation": "Google Slides not supported in v0.1",
        "application/vnd.google-apps.spreadsheet": "Google Sheets not supported in v0.1",
        "application/msword": "Microsoft Word not supported in v0.1",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Office documents not supported in v0.1",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Office documents not supported in v0.1",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "Office documents not supported in v0.1",
        "application/vnd.google-apps.folder": "Folders themselves are not files",
    }

    if mime_type in unsupported_types:
        return unsupported_types[mime_type]

    supported_types = {
        "application/pdf",
        "application/vnd.google-apps.document",
    }

    if mime_type not in supported_types:
        return f"Unsupported mime type: {mime_type}"

    return None
