import pytest

from deepfolder.chunker import Chunker


class TestChunkerPDF:
    def test_chunk_single_page(self) -> None:
        chunker = Chunker()
        pages = {1: "This is a single page with some text."}
        chunks = chunker.chunk_pdf(pages, "file123")

        assert len(chunks) == 1
        assert chunks[0].primary_unit_type == "pdf_page"
        assert chunks[0].primary_unit_value == "1"
        assert chunks[0].text == "This is a single page with some text."
        assert chunks[0].anchor_id is None
        assert chunks[0].ordinal == 0
        assert chunks[0].deep_link == "https://drive.google.com/file/d/file123/view#page=1"

    def test_chunk_multiple_pages(self) -> None:
        chunker = Chunker()
        pages = {
            1: "Page one content.",
            2: "Page two content.",
        }
        chunks = chunker.chunk_pdf(pages, "file123")

        assert len(chunks) == 2
        assert chunks[0].primary_unit_value == "1"
        assert chunks[1].primary_unit_value == "2"

    def test_chunk_hash_generated(self) -> None:
        chunker = Chunker()
        pages = {1: "Content"}
        chunks = chunker.chunk_pdf(pages, "file123")

        assert chunks[0].content_hash
        assert len(chunks[0].content_hash) == 64

    def test_chunk_token_count(self) -> None:
        chunker = Chunker()
        pages = {1: "Short text"}
        chunks = chunker.chunk_pdf(pages, "file123")

        assert chunks[0].token_count > 0

    def test_chunk_long_page_splits(self) -> None:
        chunker = Chunker()
        long_text = " ".join(["word"] * 1000)
        pages = {1: long_text}
        chunks = chunker.chunk_pdf(pages, "file123")

        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.token_count <= Chunker.MAX_CHUNK_TOKENS

    def test_chunk_order_by_page(self) -> None:
        chunker = Chunker()
        pages = {3: "Page 3", 1: "Page 1", 2: "Page 2"}
        chunks = chunker.chunk_pdf(pages, "file123")

        values = [int(chunk.primary_unit_value) for chunk in chunks]
        assert values == sorted(values)


class TestChunkerDocs:
    def test_chunk_doc_no_headings(self) -> None:
        chunker = Chunker()
        content = "This is document content without headings."
        chunks = chunker.chunk_docs(content, [], "file123")

        assert len(chunks) == 1
        assert chunks[0].primary_unit_type == "docs_heading"
        assert chunks[0].primary_unit_value == "Document"
        assert chunks[0].anchor_id is None

    def test_chunk_doc_with_headings(self) -> None:
        chunker = Chunker()
        content = "Introduction section content\nChapter 1 subsection content\nChapter 2 more content"
        headings = [
            {"text": "Introduction", "anchor_id": "h.abc123"},
            {"text": "Chapter 1", "anchor_id": "h.def456"},
        ]
        chunks = chunker.chunk_docs(content, headings, "file123")

        assert len(chunks) >= 2
        assert chunks[0].primary_unit_value == "Introduction"
        assert chunks[0].anchor_id == "h.abc123"

    def test_chunk_doc_deep_link(self) -> None:
        chunker = Chunker()
        content = "Heading section content"
        headings = [{"text": "Heading", "anchor_id": "h.xyz789"}]
        chunks = chunker.chunk_docs(content, headings, "file123")

        assert (
            chunks[0].deep_link
            == "https://docs.google.com/document/d/file123/edit#heading=h.xyz789"
        )

    def test_chunk_doc_long_section_splits(self) -> None:
        chunker = Chunker()
        long_text = " ".join(["word"] * 1000)
        content = "Heading\n" + long_text
        headings = [{"text": "Heading", "anchor_id": "h.test"}]
        chunks = chunker.chunk_docs(content, headings, "file123")

        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.token_count <= Chunker.MAX_CHUNK_TOKENS
            assert chunk.primary_unit_value == "Heading"


class TestChunkerSlides:
    def test_chunk_single_slide(self) -> None:
        chunker = Chunker()
        slides = {"g12345abc": "Welcome to the presentation"}
        chunks = chunker.chunk_slides(slides, "pres123")

        assert len(chunks) == 1
        assert chunks[0].primary_unit_type == "slide"
        assert chunks[0].primary_unit_value == "1"
        assert chunks[0].anchor_id == "g12345abc"
        assert chunks[0].ordinal == 0
        assert chunks[0].deep_link == (
            "https://docs.google.com/presentation/d/pres123/edit#slide=id.g12345abc"
        )

    def test_chunk_multiple_slides(self) -> None:
        chunker = Chunker()
        slides = {
            "g111": "Slide one content",
            "g222": "Slide two content",
            "g333": "Slide three content",
        }
        chunks = chunker.chunk_slides(slides, "pres456")

        assert len(chunks) == 3
        assert chunks[0].primary_unit_value == "1"
        assert chunks[0].anchor_id == "g111"
        assert chunks[1].primary_unit_value == "2"
        assert chunks[1].anchor_id == "g222"
        assert chunks[2].primary_unit_value == "3"
        assert chunks[2].anchor_id == "g333"

    def test_chunk_slides_empty_skipped(self) -> None:
        chunker = Chunker()
        slides = {"g111": "", "g222": "Actual content"}
        chunks = chunker.chunk_slides(slides, "pres123")

        assert len(chunks) == 1
        assert chunks[0].anchor_id == "g222"

    def test_chunk_slides_long_splits(self) -> None:
        chunker = Chunker()
        long_text = " ".join(["word"] * 1000)
        slides = {"g111": long_text}
        chunks = chunker.chunk_slides(slides, "pres123")

        assert len(chunks) > 1
        for c in chunks:
            assert c.token_count <= Chunker.MAX_CHUNK_TOKENS
            assert c.anchor_id == "g111"
            assert c.primary_unit_value == "1"

    def test_chunk_slides_content_hash(self) -> None:
        chunker = Chunker()
        slides = {"g111": "Presentation content"}
        chunks = chunker.chunk_slides(slides, "pres123")

        assert len(chunks) == 1
        assert len(chunks[0].content_hash) == 64


class TestChunkerSheets:
    def test_chunk_single_sheet(self) -> None:
        chunker = Chunker()
        sheets = [
            {"name": "Sheet1", "gid": "0", "text": "Name\tAge\nAlice\t30", "row_range": "A1:B2"},
        ]
        chunks = chunker.chunk_sheets(sheets, "sheet123")

        assert len(chunks) == 1
        assert chunks[0].primary_unit_type == "sheet_range"
        assert chunks[0].primary_unit_value == "Sheet1 (A1:B2)"
        assert chunks[0].anchor_id == "0"
        assert chunks[0].ordinal == 0
        assert chunks[0].deep_link == (
            "https://docs.google.com/spreadsheets/d/sheet123/edit#gid=0&range=A1:B2"
        )

    def test_chunk_multiple_sheets(self) -> None:
        chunker = Chunker()
        sheets = [
            {"name": "Sheet1", "gid": "0", "text": "First sheet data", "row_range": "A1:A1"},
            {"name": "Data", "gid": "123456789", "text": "Second sheet data", "row_range": "A1:C5"},
        ]
        chunks = chunker.chunk_sheets(sheets, "sheet456")

        assert len(chunks) == 2
        assert chunks[0].primary_unit_value == "Sheet1 (A1:A1)"
        assert chunks[0].anchor_id == "0"
        assert chunks[1].primary_unit_value == "Data (A1:C5)"
        assert chunks[1].anchor_id == "123456789"

    def test_chunk_sheets_empty_skipped(self) -> None:
        chunker = Chunker()
        sheets = [
            {"name": "Empty", "gid": "0", "text": "  ", "row_range": "A1:Z1"},
            {"name": "Data", "gid": "1", "text": "Has content", "row_range": "A1:B2"},
        ]
        chunks = chunker.chunk_sheets(sheets, "sheet123")

        assert len(chunks) == 1
        assert chunks[0].anchor_id == "1"

    def test_chunk_sheets_long_splits(self) -> None:
        chunker = Chunker()
        long_text = "\t".join(["word"] * 1000)
        sheets = [
            {"name": "BigSheet", "gid": "0", "text": long_text, "row_range": "A1:CVL100"},
        ]
        chunks = chunker.chunk_sheets(sheets, "sheet123")

        assert len(chunks) > 1
        for c in chunks:
            assert c.token_count <= Chunker.MAX_CHUNK_TOKENS
            assert c.anchor_id == "0"
            assert c.primary_unit_value == "BigSheet (A1:CVL100)"


class TestChunkerOverlap:
    def test_overlap_is_applied(self) -> None:
        chunker = Chunker()
        long_text = " ".join(["word"] * 1000)
        pages = {1: long_text}
        chunks = chunker.chunk_pdf(pages, "file123")

        if len(chunks) > 1:
            last_tokens_chunk_0 = chunker.tokenizer.encode(chunks[0].text)[
                -Chunker.OVERLAP_TOKENS :
            ]
            first_tokens_chunk_1 = chunker.tokenizer.encode(chunks[1].text)[
                : Chunker.OVERLAP_TOKENS
            ]

            assert last_tokens_chunk_0 == first_tokens_chunk_1


class TestChunkerContentHash:
    def test_content_hash_stable(self) -> None:
        chunker = Chunker()
        text = "Same content"
        pages1 = {1: text}
        pages2 = {1: text}

        chunks1 = chunker.chunk_pdf(pages1, "file1")
        chunks2 = chunker.chunk_pdf(pages2, "file2")

        assert chunks1[0].content_hash == chunks2[0].content_hash

    def test_content_hash_whitespace_normalized(self) -> None:
        chunker = Chunker()
        pages1 = {1: "Text   with   spaces"}
        pages2 = {1: "Text with spaces"}

        chunks1 = chunker.chunk_pdf(pages1, "file1")
        chunks2 = chunker.chunk_pdf(pages2, "file2")

        assert chunks1[0].content_hash == chunks2[0].content_hash
