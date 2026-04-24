from deepfolder.chunker import Chunker


class TestChunkerDocx:
    def test_chunk_single_section(self) -> None:
        chunker = Chunker()
        sections = [("Introduction", "This is the intro section.")]
        chunks = chunker.chunk_docx(sections, "file123")

        assert len(chunks) == 1
        assert chunks[0].primary_unit_type == "docx_heading"
        assert chunks[0].primary_unit_value == "Introduction"
        assert chunks[0].anchor_id is None
        assert chunks[0].deep_link == "https://drive.google.com/file/d/file123/view"
        assert chunks[0].ordinal == 0

    def test_chunk_multiple_sections(self) -> None:
        chunker = Chunker()
        sections = [
            ("Heading 1", "Content of section 1."),
            ("Heading 2", "Content of section 2."),
        ]
        chunks = chunker.chunk_docx(sections, "file123")

        assert len(chunks) == 2
        assert chunks[0].primary_unit_value == "Heading 1"
        assert chunks[1].primary_unit_value == "Heading 2"
        assert chunks[0].deep_link == chunks[1].deep_link

    def test_chunk_long_section_splits(self) -> None:
        chunker = Chunker()
        long_text = " ".join(["word"] * 1000)
        sections = [("Long Section", long_text)]
        chunks = chunker.chunk_docx(sections, "file123")

        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.token_count <= Chunker.MAX_CHUNK_TOKENS
            assert chunk.primary_unit_value == "Long Section"

    def test_chunk_content_hash(self) -> None:
        chunker = Chunker()
        sections = [("Section", "Some content here.")]
        chunks = chunker.chunk_docx(sections, "file123")

        assert chunks[0].content_hash
        assert len(chunks[0].content_hash) == 64


class TestChunkerPptx:
    def test_chunk_single_slide(self) -> None:
        chunker = Chunker()
        slides = {1: "Content of slide 1."}
        chunks = chunker.chunk_pptx(slides, "file123")

        assert len(chunks) == 1
        assert chunks[0].primary_unit_type == "pptx_slide"
        assert chunks[0].primary_unit_value == "1"
        assert chunks[0].anchor_id is None
        assert chunks[0].deep_link == "https://drive.google.com/file/d/file123/view"
        assert chunks[0].ordinal == 0

    def test_chunk_multiple_slides(self) -> None:
        chunker = Chunker()
        slides = {1: "Slide 1.", 2: "Slide 2."}
        chunks = chunker.chunk_pptx(slides, "file123")

        assert len(chunks) == 2
        assert chunks[0].primary_unit_value == "1"
        assert chunks[1].primary_unit_value == "2"

    def test_chunk_slides_ordered(self) -> None:
        chunker = Chunker()
        slides = {3: "Slide 3", 1: "Slide 1", 2: "Slide 2"}
        chunks = chunker.chunk_pptx(slides, "file123")

        values = [int(c.primary_unit_value) for c in chunks]
        assert values == sorted(values)

    def test_chunk_long_slide_splits(self) -> None:
        chunker = Chunker()
        long_text = " ".join(["word"] * 1000)
        slides = {1: long_text}
        chunks = chunker.chunk_pptx(slides, "file123")

        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.token_count <= Chunker.MAX_CHUNK_TOKENS


class TestChunkerXlsx:
    def test_chunk_single_sheet(self) -> None:
        chunker = Chunker()
        sheets = {"Sheet1": "A1\tB1\nA2\tB2"}
        chunks = chunker.chunk_xlsx(sheets, "file123")

        assert len(chunks) == 1
        assert chunks[0].primary_unit_type == "xlsx_sheet"
        assert chunks[0].primary_unit_value == "Sheet1"
        assert chunks[0].anchor_id is None
        assert chunks[0].deep_link == "https://drive.google.com/file/d/file123/view"

    def test_chunk_multiple_sheets(self) -> None:
        chunker = Chunker()
        sheets = {"Sheet1": "Data 1", "Sheet2": "Data 2"}
        chunks = chunker.chunk_xlsx(sheets, "file123")

        assert len(chunks) == 2
        values = {c.primary_unit_value for c in chunks}
        assert values == {"Sheet1", "Sheet2"}

    def test_chunk_long_sheet_splits(self) -> None:
        chunker = Chunker()
        long_text = " ".join(["word"] * 1000)
        sheets = {"Sheet1": long_text}
        chunks = chunker.chunk_xlsx(sheets, "file123")

        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.token_count <= Chunker.MAX_CHUNK_TOKENS
            assert chunk.primary_unit_value == "Sheet1"
