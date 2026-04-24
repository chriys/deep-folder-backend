from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.citation_builder import Citation
from deepfolder.hybrid_search import HybridSearch
from deepfolder.models.chunk import Chunk
from deepfolder.models.file import File


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


@pytest.mark.asyncio
async def test_bm25_search_rank_order(
    postgres_db: str,
    async_session: AsyncSession,
) -> None:
    """Insert known chunks and verify BM25 relevance rank order via ts_rank_cd."""
    search = HybridSearch()

    # Set up tsvector trigger normally created by migration 0012
    await async_session.execute(text("""
        CREATE OR REPLACE FUNCTION chunks_search_vector_update()
        RETURNS trigger AS $$
        BEGIN
          NEW.search_vector := to_tsvector('english', NEW.text);
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    await async_session.execute(text("""
        DROP TRIGGER IF EXISTS trg_chunks_search_vector ON chunks
    """))
    await async_session.execute(text("""
        CREATE TRIGGER trg_chunks_search_vector
        BEFORE INSERT OR UPDATE OF text ON chunks
        FOR EACH ROW EXECUTE FUNCTION chunks_search_vector_update()
    """))
    await async_session.commit()

    # Insert folder
    folder = await async_session.execute(
        text("INSERT INTO folders (user_id, drive_folder_id, name, state, file_count) "
             "VALUES (1, 'folder_1', 'Test Folder', 'ready', 0) RETURNING id")
    )
    folder_id = folder.scalar_one()

    # Insert file
    file = await async_session.execute(
        text("INSERT INTO files (folder_id, drive_file_id, name, mime_type, modified_time) "
             "VALUES (:fid, 'file_1', 'test.pdf', 'application/pdf', NOW()) RETURNING id"),
        {"fid": folder_id},
    )
    file_id = file.scalar_one()

    # Insert chunks with different keyword relevance
    chunks_text = [
        "the cat sat on a large mat in the sunny room",
        "dogs and cats are both popular household pets",
        "quantum physics describes the behavior of subatomic particles",
        "the stock market had a volatile trading session today",
    ]
    for i, chunk_text in enumerate(chunks_text):
        await async_session.execute(
            text(
                "INSERT INTO chunks "
                "(file_id, primary_unit_type, primary_unit_value, text, content_hash, "
                " token_count, deep_link, ordinal) "
                "VALUES (:fid, :type, :val, :text, :hash, :tcount, :link, :ord)"
            ),
            {
                "fid": file_id,
                "type": "test",
                "val": str(i),
                "text": chunk_text,
                "hash": f"hash{i}",
                "tcount": len(chunk_text.split()),
                "link": "https://example.com",
                "ord": i,
            },
        )
    await async_session.commit()

    # Search for "cat" — chunks 0 and 1 contain cat/cats
    results = await search._bm25_search(async_session, folder_id, "cat", k=10)

    assert len(results) >= 2
    chunk0, score0, _ = results[0]
    chunk1, score1, _ = results[1]
    assert chunk0.ordinal == 0  # "cat sat on a large mat" — "cat" is more central
    assert chunk1.ordinal == 1  # "dogs and cats" — stemmed match on "cats"
    assert score0 > 0, "ts_rank_cd should produce a positive score for matching chunk"
    assert score0 + score1 > 0, "combined rank scores should be positive"
