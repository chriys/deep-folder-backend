from datetime import datetime, timezone

from deepfolder.models.chunk import Chunk
from deepfolder.citation_builder import CitationBuilder, Citation, PrimaryUnit


def test_citation_builder_from_chunk() -> None:
    chunk = Chunk(
        id=123,
        file_id=456,
        primary_unit_type="pdf_page",
        primary_unit_value="42",
        text="Sample chunk text",
        content_hash="abc123",
        token_count=100,
        anchor_id=None,
        deep_link="https://drive.google.com/file/d/xyz/view#page=42",
        ordinal=0,
        created_at=datetime.now(timezone.utc),
    )

    citation = CitationBuilder.build(chunk, "My PDF File.pdf")

    assert citation.chunk_id == 123
    assert citation.file_id == 456
    assert citation.file_name == "My PDF File.pdf"
    assert citation.primary_unit.type == "pdf_page"
    assert citation.primary_unit.value == "42"
    assert citation.quote == "Sample chunk text"
    assert citation.deep_link == "https://drive.google.com/file/d/xyz/view#page=42"


def test_citation_to_dict() -> None:
    chunk = Chunk(
        id=1,
        file_id=2,
        primary_unit_type="docs_heading",
        primary_unit_value="Chapter 1",
        text="Chapter content",
        content_hash="def456",
        token_count=50,
        anchor_id="h.abc123",
        deep_link="https://docs.google.com/document/d/xyz/edit#heading=h.abc123",
        ordinal=0,
        created_at=datetime.now(timezone.utc),
    )

    citation = CitationBuilder.build(chunk, "Document.docx")
    citation_dict = citation.to_dict()

    assert citation_dict["chunk_id"] == 1
    assert citation_dict["file_id"] == 2
    assert citation_dict["file_name"] == "Document.docx"
    assert citation_dict["primary_unit"]["type"] == "docs_heading"
    assert citation_dict["primary_unit"]["value"] == "Chapter 1"
    assert citation_dict["quote"] == "Chapter content"
    assert citation_dict["deep_link"] == "https://docs.google.com/document/d/xyz/edit#heading=h.abc123"


def test_citation_primary_unit_dataclass() -> None:
    unit = PrimaryUnit(type="pdf_page", value="10")

    assert unit.type == "pdf_page"
    assert unit.value == "10"
