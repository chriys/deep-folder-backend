import asyncio
from typing import Any
from io import BytesIO

from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


class PDFExtractor:
    @staticmethod
    async def extract_text(file_content: bytes) -> dict[int, str]:
        """Extract text from PDF by page. Returns dict of {page_num: text}."""
        try:
            import pypdf
        except ImportError:
            raise ImportError("pypdf is required for PDF extraction")

        def _extract() -> dict[int, str]:
            reader = pypdf.PdfReader(BytesIO(file_content))
            pages = {}
            for page_num, page in enumerate(reader.pages, 1):
                pages[page_num] = page.extract_text()
            return pages

        return await asyncio.to_thread(_extract)


class GoogleDocsExtractor:
    @staticmethod
    async def extract_text(
        file_id: str, credentials: Credentials
    ) -> str:
        """Extract text from Google Doc using export."""
        service = build("drive", "v3", credentials=credentials)

        def _extract() -> str:
            try:
                request = service.files().export_media(
                    fileId=file_id, mimeType="text/plain"
                )
                fh = BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                return fh.getvalue().decode("utf-8")
            except Exception as e:
                raise ValueError(f"Error extracting Google Doc {file_id}: {e}")

        return await asyncio.to_thread(_extract)
