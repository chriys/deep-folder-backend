import hashlib
import re
from dataclasses import dataclass

import tiktoken


@dataclass
class ChunkData:
    primary_unit_type: str
    primary_unit_value: str
    text: str
    content_hash: str
    token_count: int
    anchor_id: str | None
    deep_link: str
    ordinal: int


class Chunker:
    MAX_CHUNK_TOKENS = 512
    OVERLAP_TOKENS = 64
    ENCODING = "cl100k_base"

    def __init__(self) -> None:
        self.tokenizer = tiktoken.get_encoding(self.ENCODING)

    def chunk_pdf(
        self, pages: dict[int, str], drive_file_id: str
    ) -> list[ChunkData]:
        chunks: list[ChunkData] = []
        ordinal = 0

        for page_num, text in sorted(pages.items()):
            page_chunks = self._chunk_text(
                text,
                primary_unit_type="pdf_page",
                primary_unit_value=str(page_num),
                anchor_id=None,
                deep_link=f"https://drive.google.com/file/d/{drive_file_id}/view#page={page_num}",
                start_ordinal=ordinal,
            )
            chunks.extend(page_chunks)
            ordinal += len(page_chunks)

        return chunks

    def chunk_slides(
        self, slides: dict[str, str], drive_file_id: str
    ) -> list[ChunkData]:
        """Chunk Google Slides content, one entry per slide keyed by objectId."""
        chunks: list[ChunkData] = []
        ordinal = 0
        slides_list = list(slides.items())
        for slide_num, (object_id, text) in enumerate(slides_list, 1):
            slide_chunks = self._chunk_text(
                text,
                primary_unit_type="slide",
                primary_unit_value=str(slide_num),
                anchor_id=object_id,
                deep_link=f"https://docs.google.com/presentation/d/{drive_file_id}/edit#slide=id.{object_id}",
                start_ordinal=ordinal,
            )
            chunks.extend(slide_chunks)
            ordinal += len(slide_chunks)
        return chunks

    def chunk_sheets(
        self, sheets: list[dict[str, str]], drive_file_id: str
    ) -> list[ChunkData]:
        """Chunk Google Sheets content, one entry per sheet.
        sheets: list of {name, gid, text, row_range} dicts
        """
        chunks: list[ChunkData] = []
        ordinal = 0
        for sheet_data in sheets:
            name = sheet_data["name"]
            gid = sheet_data["gid"]
            text = sheet_data["text"]
            row_range = sheet_data["row_range"]

            sheet_chunks = self._chunk_text(
                text,
                primary_unit_type="sheet_range",
                primary_unit_value=f"{name} ({row_range})",
                anchor_id=gid,
                deep_link=f"https://docs.google.com/spreadsheets/d/{drive_file_id}/edit#gid={gid}&range={row_range}",
                start_ordinal=ordinal,
            )
            chunks.extend(sheet_chunks)
            ordinal += len(sheet_chunks)
        return chunks

    def chunk_docs(
        self, content: str, headings: list[dict[str, str]], drive_file_id: str
    ) -> list[ChunkData]:
        """
        Chunk Google Docs content by headings.
        headings: list of {text, anchor_id} dicts in order of appearance
        """
        chunks: list[ChunkData] = []
        ordinal = 0

        if not headings:
            heading_chunks = self._chunk_text(
                content,
                primary_unit_type="docs_heading",
                primary_unit_value="Document",
                anchor_id=None,
                deep_link=f"https://docs.google.com/document/d/{drive_file_id}/edit",
                start_ordinal=ordinal,
            )
            chunks.extend(heading_chunks)
            ordinal += len(heading_chunks)
            return chunks

        current_pos = 0
        for i, heading_info in enumerate(headings):
            heading_text = heading_info["text"]
            anchor_id = heading_info["anchor_id"]

            heading_index = content.find(heading_text, current_pos)
            if heading_index == -1:
                continue

            next_heading_pos = len(content)
            if i + 1 < len(headings):
                next_heading_text = headings[i + 1]["text"]
                next_pos = content.find(next_heading_text, heading_index + 1)
                if next_pos != -1:
                    next_heading_pos = next_pos

            section_text = content[heading_index:next_heading_pos].strip()
            current_pos = next_heading_pos

            heading_chunks = self._chunk_text(
                section_text,
                primary_unit_type="docs_heading",
                primary_unit_value=heading_text,
                anchor_id=anchor_id,
                deep_link=f"https://docs.google.com/document/d/{drive_file_id}/edit#heading={anchor_id}",
                start_ordinal=ordinal,
            )
            chunks.extend(heading_chunks)
            ordinal += len(heading_chunks)

        return chunks

    def _chunk_text(
        self,
        text: str,
        primary_unit_type: str,
        primary_unit_value: str,
        anchor_id: str | None,
        deep_link: str,
        start_ordinal: int,
    ) -> list[ChunkData]:
        text = text.strip()
        if not text:
            return []

        tokens = self.tokenizer.encode(text)

        if len(tokens) <= self.MAX_CHUNK_TOKENS:
            return [
                ChunkData(
                    primary_unit_type=primary_unit_type,
                    primary_unit_value=primary_unit_value,
                    text=text,
                    content_hash=self._hash_text(text),
                    token_count=len(tokens),
                    anchor_id=anchor_id,
                    deep_link=deep_link,
                    ordinal=start_ordinal,
                )
            ]

        chunks: list[ChunkData] = []
        i = 0
        ordinal = start_ordinal

        while i < len(tokens):
            end = min(i + self.MAX_CHUNK_TOKENS, len(tokens))
            chunk_tokens = tokens[i:end]

            chunk_text = self.tokenizer.decode(chunk_tokens)

            chunks.append(
                ChunkData(
                    primary_unit_type=primary_unit_type,
                    primary_unit_value=primary_unit_value,
                    text=chunk_text,
                    content_hash=self._hash_text(chunk_text),
                    token_count=len(chunk_tokens),
                    anchor_id=anchor_id,
                    deep_link=deep_link,
                    ordinal=ordinal,
                )
            )
            ordinal += 1

            if end >= len(tokens):
                break

            i = end - self.OVERLAP_TOKENS

        return chunks

    @staticmethod
    def _hash_text(text: str) -> str:
        normalized = re.sub(r"\s+", " ", text.strip())
        return hashlib.sha256(normalized.encode()).hexdigest()
