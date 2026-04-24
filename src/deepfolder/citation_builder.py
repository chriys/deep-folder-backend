from dataclasses import asdict, dataclass
from typing import Any

from deepfolder.models.chunk import Chunk


@dataclass
class PrimaryUnit:
    type: str
    value: str


@dataclass
class Citation:
    chunk_id: int
    file_id: int
    file_name: str
    primary_unit: PrimaryUnit
    quote: str
    deep_link: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "file_id": self.file_id,
            "file_name": self.file_name,
            "primary_unit": asdict(self.primary_unit),
            "quote": self.quote,
            "deep_link": self.deep_link,
        }


class CitationBuilder:
    @staticmethod
    def build(chunk: Chunk, file_name: str) -> Citation:
        """Build a Citation from a Chunk row.

    Note: Office files (docx/pptx/xlsx) stored in Drive use file-level
    deep links only. No section-level anchors are available for these
    formats due to the absence of a Drive-native anchor system.
    """
        return Citation(
            chunk_id=chunk.id,
            file_id=chunk.file_id,
            file_name=file_name,
            primary_unit=PrimaryUnit(
                type=chunk.primary_unit_type,
                value=chunk.primary_unit_value,
            ),
            quote=chunk.text,
            deep_link=chunk.deep_link,
        )
