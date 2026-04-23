import asyncio
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse, parse_qs

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


class DriveClient:
    def __init__(self, client_id: str = "", client_secret: str = ""):
        self.client_id = client_id
        self.client_secret = client_secret

    def parse_folder_url(self, url: str) -> str:
        url = url.strip()

        if url.startswith("0A"):
            raise ValueError("Shared Drives not yet supported")

        match = re.search(r"/folders/([a-zA-Z0-9_-]+)", url)
        if match:
            folder_id = match.group(1)
            if folder_id.startswith("0A"):
                raise ValueError("Shared Drives not yet supported")
            return folder_id

        if "/" not in url and "?" not in url:
            if url.startswith("0A"):
                raise ValueError("Shared Drives not yet supported")
            return url

        raise ValueError("Invalid folder URL")

    def get_drive_service(self, credentials: Credentials) -> Any:
        """Build and return Google Drive service."""
        return build("drive", "v3", credentials=credentials)

    async def list_folder_recursive(
        self,
        folder_id: str,
        credentials: Credentials,
        max_depth: int = 5,
        max_files: int = 500,
    ) -> list[dict[str, Any]]:
        """Recursively list files in a Drive folder with depth and file limits."""
        if max_depth > 5:
            raise ValueError("Depth limit exceeded: max 5")
        if max_files > 500:
            raise ValueError("File limit exceeded: max 500")

        service = self.get_drive_service(credentials)
        all_files: list[dict[str, Any]] = []

        async def _list_recursive(
            current_folder_id: str, current_depth: int, remaining_files: int
        ) -> int:
            if current_depth > max_depth or remaining_files <= 0:
                return remaining_files

            try:
                query = f"'{current_folder_id}' in parents and trashed=false"

                def _execute_query() -> dict[str, Any]:
                    return (
                        service.files()
                        .list(
                            q=query,
                            spaces="drive",
                            fields="files(id, name, mimeType, modifiedTime)",
                            pageSize=1000,
                        )
                        .execute()
                    )

                results = await asyncio.to_thread(_execute_query)
                files = results.get("files", [])

                for file_item in files:
                    if remaining_files <= 0:
                        break

                    all_files.append(file_item)
                    remaining_files -= 1

                    if file_item["mimeType"] == "application/vnd.google-apps.folder":
                        remaining_files = await _list_recursive(
                            file_item["id"], current_depth + 1, remaining_files
                        )

                return remaining_files
            except Exception as e:
                raise ValueError(f"Error listing folder {current_folder_id}: {e}")

        remaining = await _list_recursive(folder_id, 0, max_files)
        if remaining < 0:
            raise ValueError("File limit exceeded: max 500")

        return all_files
