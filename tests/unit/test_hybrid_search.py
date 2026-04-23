from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.hybrid_search import HybridSearch
from deepfolder.models.chunk import Chunk
from deepfolder.models.file import File
from deepfolder.citation_builder import Citation


@pytest.mark.asyncio
async def test_retrieve_returns_tuples() -> None:
    search = HybridSearch()
    session = AsyncMock(spec=AsyncSession)
    folder_id = 1
    query = "test query"

    mock_file = MagicMock(spec=File)
    mock_file.name = "test.pdf"

    mock_chunk = MagicMock(spec=Chunk)
    mock_chunk.id = 1
    mock_chunk.file_id = 1
    mock_chunk.text = "Test text"
    mock_chunk.deep_link = "https://example.com"
    mock_chunk.primary_unit_type = "pdf_page"
    mock_chunk.primary_unit_value = "1"

    with pytest.MonkeyPatch.context() as m:
        m.setattr(
            search,
            "_embed_query",
            AsyncMock(return_value=[0.1] * 1024)
        )
        m.setattr(
            search,
            "_search_vectors",
            AsyncMock(return_value=[(mock_chunk, 0.95, mock_file)])
        )

        results = await search.retrieve(session, folder_id, query, k=10)

        assert len(results) == 1
        chunk, score, citation = results[0]
        assert chunk == mock_chunk
        assert isinstance(score, float)
        assert isinstance(citation, Citation)


@pytest.mark.asyncio
async def test_retrieve_respects_k_limit() -> None:
    search = HybridSearch()
    session = AsyncMock(spec=AsyncSession)
    folder_id = 1
    query = "test query"
    k = 5

    mock_file = MagicMock(spec=File)
    mock_file.name = "test.pdf"

    mock_chunks = []
    for i in range(10):
        chunk = MagicMock(spec=Chunk)
        chunk.id = i
        chunk.file_id = 1
        chunk.text = f"Text {i}"
        chunk.deep_link = "https://example.com"
        chunk.primary_unit_type = "pdf_page"
        chunk.primary_unit_value = str(i)
        mock_chunks.append((chunk, 0.9 - i * 0.01, mock_file))

    with pytest.MonkeyPatch.context() as m:
        m.setattr(
            search,
            "_embed_query",
            AsyncMock(return_value=[0.1] * 1024)
        )
        m.setattr(
            search,
            "_search_vectors",
            AsyncMock(return_value=mock_chunks)
        )

        results = await search.retrieve(session, folder_id, query, k=k)

        assert len(results) == k


@pytest.mark.asyncio
async def test_retrieve_returns_empty_list() -> None:
    search = HybridSearch()
    session = AsyncMock(spec=AsyncSession)
    folder_id = 1
    query = "test query"

    with pytest.MonkeyPatch.context() as m:
        m.setattr(
            search,
            "_embed_query",
            AsyncMock(return_value=[0.1] * 1024)
        )
        m.setattr(
            search,
            "_search_vectors",
            AsyncMock(return_value=[])
        )

        results = await search.retrieve(session, folder_id, query, k=10)

        assert results == []
