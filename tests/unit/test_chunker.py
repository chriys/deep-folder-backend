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
