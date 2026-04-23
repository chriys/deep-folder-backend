import asyncio
import hashlib
import re
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

    @staticmethod
    async def extract_with_headings(
        file_id: str, credentials: Credentials
    ) -> tuple[str, list[dict[str, str]]]:
        """Extract text and heading structure from Google Doc.
        Returns (text, list of {text, anchor_id} dicts)."""
        service = build("docs", "v1", credentials=credentials)

        def _extract() -> tuple[str, list[dict[str, str]]]:
            try:
                doc = service.documents().get(documentId=file_id).execute()
                text = GoogleDocsExtractor._extract_text_from_document(doc)
                headings = GoogleDocsExtractor._extract_headings_from_document(doc)
                return text, headings
            except Exception as e:
                raise ValueError(f"Error extracting Google Doc {file_id}: {e}")

        return await asyncio.to_thread(_extract)

    @staticmethod
    def _extract_text_from_document(doc: dict[str, Any]) -> str:
        """Extract plain text from Google Doc structure."""
        text_parts = []
        for element in doc.get("body", {}).get("content", []):
            if "paragraph" in element:
                para = element["paragraph"]
                for run in para.get("elements", []):
                    if "textRun" in run:
                        text_parts.append(run["textRun"]["content"])
        return "".join(text_parts)

    @staticmethod
    def _extract_headings_from_document(doc: dict[str, Any]) -> list[dict[str, str]]:
        """Extract headings with anchor IDs from Google Doc structure."""
        headings: list[dict[str, str]] = []
        for element in doc.get("body", {}).get("content", []):
            if "paragraph" in element:
                para = element["paragraph"]
                style = para.get("paragraphStyle", {})
                heading_id = style.get("headingId")

                if heading_id:
                    text_parts = []
                    for run in para.get("elements", []):
                        if "textRun" in run:
                            text_parts.append(run["textRun"]["content"])
                    heading_text = "".join(text_parts).strip()
                    if heading_text:
                        headings.append({"text": heading_text, "anchor_id": heading_id})

        return headings
