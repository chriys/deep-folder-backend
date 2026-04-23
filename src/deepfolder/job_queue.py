from datetime import datetime, timezone, timedelta
from typing import Any, Callable
from io import BytesIO

from google.oauth2.credentials import Credentials
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.discovery import build

from deepfolder.auth.token_vault import TokenVault
from deepfolder.config import settings
from deepfolder.drive_client import DriveClient
from deepfolder.embedding_client import EmbeddingClient
from deepfolder.models.folder import Folder
from deepfolder.models.file import File
from deepfolder.models.skipped_file import SkippedFile
from deepfolder.models.job import Job
from deepfolder.models.user import User
from deepfolder.models.chunk import Chunk
from deepfolder.extractors import PDFExtractor, GoogleDocsExtractor
from deepfolder.chunker import Chunker
from deepfolder.usage_tracker import UsageTracker, SpendCapExceeded


class JobQueue:
    @staticmethod
    async def dequeue_job(session: AsyncSession) -> Job | None:
        """Get the next pending job that's ready to run.

        Uses FOR UPDATE SKIP LOCKED to allow concurrent workers to claim jobs
        without blocking each other. Only one worker will claim each job.
        """
        result = await session.execute(
            select(Job)
            .where(
                (Job.status == "pending")
                & (Job.run_after <= datetime.now(timezone.utc))
            )
            .order_by(Job.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
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
    def register(cls, kind: str) -> Callable:
        """Decorator to register a job handler."""
        def decorator(func: Callable) -> Callable:
            cls._handlers[kind] = func
            return func
        return decorator

    @classmethod
    async def execute(cls, session: AsyncSession, job: Job) -> None:
        """Execute a job by its type."""
        handler = cls._handlers.get(job.kind)
        if not handler:
            raise ValueError(f"No handler registered for job kind: {job.kind}")
        await handler(session, job)


@JobHandlers.register("ingest_folder")
async def handle_ingest_folder(session: AsyncSession, job: Job) -> None:
    """Ingest a Drive folder: list files, extract text, chunk, and persist."""
    payload = job.payload
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
        chunker = Chunker()
        drive_service = build("drive", "v3", credentials=credentials)

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
                await session.flush()

                try:
                    await _extract_and_chunk_file(
                        session,
                        file_obj,
                        mime_type,
                        drive_service,
                        credentials,
                        chunker,
                    )
                    file_obj.extracted_at = datetime.now(timezone.utc)
                    file_count += 1
                except Exception:
                    pass

        await session.commit()

        await _embed_chunks_for_folder(session, folder.id, folder.user_id)

        folder.state = "ready"
        folder.file_count = file_count
        await session.commit()

    except Exception as e:
        folder.state = "failed"
        folder.file_count = 0
        await session.commit()
        raise


async def _extract_and_chunk_file(
    session: AsyncSession,
    file_obj: File,
    mime_type: str,
    drive_service: Any,
    credentials: Credentials,
    chunker: Chunker,
) -> None:
    """Extract text from file and create chunks."""
    if mime_type == "application/pdf":
        await _extract_and_chunk_pdf(session, file_obj, drive_service, chunker)
    elif mime_type == "application/vnd.google-apps.document":
        await _extract_and_chunk_docs(session, file_obj, credentials, chunker)


async def _extract_and_chunk_pdf(
    session: AsyncSession,
    file_obj: File,
    drive_service: Any,
    chunker: Chunker,
) -> None:
    """Download and chunk PDF file."""
    request = drive_service.files().get_media(fileId=file_obj.drive_file_id)
    fh = BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    file_content = fh.getvalue()
    pages = await PDFExtractor.extract_text(file_content)
    chunks = chunker.chunk_pdf(pages, file_obj.drive_file_id)

    for chunk_data in chunks:
        chunk = Chunk(
            file_id=file_obj.id,
            primary_unit_type=chunk_data.primary_unit_type,
            primary_unit_value=chunk_data.primary_unit_value,
            text=chunk_data.text,
            content_hash=chunk_data.content_hash,
            token_count=chunk_data.token_count,
            anchor_id=chunk_data.anchor_id,
            deep_link=chunk_data.deep_link,
            ordinal=chunk_data.ordinal,
        )
        session.add(chunk)

    await session.flush()


async def _extract_and_chunk_docs(
    session: AsyncSession,
    file_obj: File,
    credentials: Credentials,
    chunker: Chunker,
) -> None:
    """Extract and chunk Google Doc file."""
    text, headings = await GoogleDocsExtractor.extract_with_headings(
        file_obj.drive_file_id, credentials
    )
    chunks = chunker.chunk_docs(text, headings, file_obj.drive_file_id)

    for chunk_data in chunks:
        chunk = Chunk(
            file_id=file_obj.id,
            primary_unit_type=chunk_data.primary_unit_type,
            primary_unit_value=chunk_data.primary_unit_value,
            text=chunk_data.text,
            content_hash=chunk_data.content_hash,
            token_count=chunk_data.token_count,
            anchor_id=chunk_data.anchor_id,
            deep_link=chunk_data.deep_link,
            ordinal=chunk_data.ordinal,
        )
        session.add(chunk)

    await session.flush()


@JobHandlers.register("sync_folder")
async def handle_sync_folder(session: AsyncSession, job: Job) -> None:
    """Sync a Drive folder: diff against database, add new files, remove deleted files."""
    payload = job.payload
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
        vault = TokenVault(settings.secret_key)
        refresh_token = vault.decrypt(user.encrypted_refresh_token)
        credentials = Credentials(token=None, refresh_token=refresh_token)

        client = DriveClient()
        drive_files = await client.list_folder_recursive(
            folder.drive_folder_id, credentials, max_depth=5, max_files=500
        )

        current_db_files = await session.execute(
            select(File).where(File.folder_id == folder.id)
        )
        db_files_dict = {f.drive_file_id: f for f in current_db_files.scalars()}

        drive_file_ids = {f["id"] for f in drive_files}
        db_file_ids = set(db_files_dict.keys())

        added_ids = drive_file_ids - db_file_ids
        removed_ids = db_file_ids - drive_file_ids

        added_count = 0
        removed_count = 0

        for file_item in drive_files:
            file_id = file_item["id"]
            if file_id not in added_ids:
                continue

            mime_type = file_item.get("mimeType", "application/octet-stream")
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
                continue

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
            added_count += 1

        for file_id in removed_ids:
            file_obj = db_files_dict[file_id]
            session.delete(file_obj)
            removed_count += 1

        await session.commit()

        new_file_count = len(db_file_ids) - removed_count + added_count
        folder.file_count = new_file_count
        await session.commit()

    except Exception as e:
        raise


async def _embed_chunks_for_folder(session: AsyncSession, folder_id: int, user_id: int) -> None:
    """Batch embed all chunks in a folder."""
    result = await session.execute(
        select(Chunk).join(File).where(File.folder_id == folder_id)
    )
    chunks = result.scalars().all()

    if not chunks:
        return

    tracker = UsageTracker(session, user_id)
    await tracker.check_spend_cap()

    texts = [chunk.text for chunk in chunks]
    embedding_client = EmbeddingClient(api_key=settings.voyage_api_key)
    embeddings, total_tokens = await embedding_client.embed_chunks(texts)

    await tracker.record("embedding", settings.embedding_model, input_tokens=total_tokens, output_tokens=0)

    for chunk, embedding in zip(chunks, embeddings):
        chunk.embedding = embedding

    await session.commit()


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
