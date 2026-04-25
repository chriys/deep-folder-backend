from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.auth.dependencies import require_user
from deepfolder.db import get_session
from deepfolder.drive_client import DriveClient
from deepfolder.models.folder import Folder
from deepfolder.models.job import Job
from deepfolder.models.user import User


router = APIRouter(prefix="/folders", tags=["folders"])


class FolderResponse(BaseModel):
    id: str
    drive_url: str
    ingest_state: str
    file_count: int
    skipped_file_count: int = 0
    error_message: str | None = None
    created_at: datetime

    @classmethod
    def from_model(cls, folder: Folder) -> "FolderResponse":
        return cls(
            id=str(folder.id),
            drive_url=f"https://drive.google.com/drive/folders/{folder.drive_folder_id}",
            ingest_state=folder.state,
            file_count=folder.file_count,
            skipped_file_count=0,
            error_message=None,
            created_at=folder.created_at,
        )


@router.post("")
async def create_folder(
    payload: dict,
    user: User = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create a folder from a Google Drive URL and enqueue ingest job."""
    drive_url = payload.get("drive_url", "")
    if not drive_url:
        raise HTTPException(status_code=400, detail="drive_url is required")

    drive_client = DriveClient()
    try:
        folder_id = drive_client.parse_folder_url(drive_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    existing = await session.execute(
        select(Folder).where(Folder.drive_folder_id == folder_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Folder already exists")

    folder = Folder(
        user_id=user.id,
        drive_folder_id=folder_id,
        name=folder_id,
        state="pending",
        file_count=0,
    )
    session.add(folder)
    await session.flush()

    job = Job(
        kind="ingest_folder",
        status="pending",
        payload={"folder_id": folder.id, "user_id": user.id},
    )
    session.add(job)
    await session.commit()

    return FolderResponse.from_model(folder).model_dump(mode="json")


@router.get("")
async def list_folders(
    user: User = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> list:
    """List all folders for the current user."""
    result = await session.execute(
        select(Folder).where(Folder.user_id == user.id)
    )
    folders = result.scalars().all()
    return [FolderResponse.from_model(f).model_dump(mode="json") for f in folders]


@router.get("/{folder_id}")
async def get_folder(
    folder_id: int,
    user: User = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get a specific folder by ID."""
    result = await session.execute(
        select(Folder).where(
            (Folder.id == folder_id) & (Folder.user_id == user.id)
        )
    )
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    return FolderResponse.from_model(folder).model_dump(mode="json")


@router.delete("/{folder_id}")
async def delete_folder(
    folder_id: int,
    user: User = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Delete a folder and cascade delete related records."""
    result = await session.execute(
        select(Folder).where(
            (Folder.id == folder_id) & (Folder.user_id == user.id)
        )
    )
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    await session.execute(delete(Folder).where(Folder.id == folder_id))
    await session.commit()

    return {"status": "deleted"}


@router.post("/{folder_id}/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync_folder(
    folder_id: int,
    user: User = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Trigger a manual sync of a folder."""
    result = await session.execute(
        select(Folder).where(
            (Folder.id == folder_id) & (Folder.user_id == user.id)
        )
    )
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    existing_jobs = await session.execute(
        select(Job).where(
            and_(
                Job.status == "pending",
                or_(
                    Job.kind == "sync_folder",
                    Job.kind == "ingest_folder"
                ),
            )
        )
    )

    for job in existing_jobs.scalars():
        if job.payload.get("folder_id") == folder_id:
            raise HTTPException(status_code=409, detail="Sync or ingest already in progress")

    job = Job(
        kind="sync_folder",
        status="pending",
        payload={"folder_id": folder_id, "user_id": user.id},
    )
    session.add(job)
    await session.commit()

    return {"job_id": job.id, "status": "accepted"}
