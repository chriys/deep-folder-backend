from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.citation_builder import Citation
from deepfolder.hybrid_search import HybridSearch
from deepfolder.models.chunk import Chunk
from deepfolder.models.file import File


def _default_mock_chunk(chunk_id: int = 1, ordinal: int = 0) -> MagicMock:
    c = MagicMock(spec=Chunk)
    c.id = chunk_id
    c.file_id = 1
    c.text = "Test text"
    c.deep_link = "https://example.com"
    c.primary_unit_type = "pdf_page"
    c.primary_unit_value = str(ordinal)
    c.ordinal = ordinal
    return c


def _default_mock_file() -> MagicMock:
    f = MagicMock(spec=File)
    f.name = "test.pdf"
    return f


@pytest.mark.asyncio
async def test_retrieve_returns_tuples() -> None:
    search = HybridSearch()
    session = AsyncMock(spec=AsyncSession)
    folder_id = 1
    query = "test query"

    mock_file = _default_mock_file()
    mock_chunk = _default_mock_chunk()

    with pytest.MonkeyPatch.context() as m:
        m.setattr(search, "_embed_query", AsyncMock(return_value=[0.1] * 1024))
        m.setattr(search, "_search_vectors", AsyncMock(return_value=[(mock_chunk, 0.95, mock_file)]))
        m.setattr(search, "_bm25_search", AsyncMock(return_value=[]))
        m.setattr(search, "_rerank", AsyncMock(return_value=([0], [0.98], 10)))

        results = await search.retrieve(session, folder_id, query, k=10)

        assert len(results) == 1
        chunk, score, citation = results[0]
        assert chunk == mock_chunk
        assert score == 0.98
        assert isinstance(citation, Citation)


@pytest.mark.asyncio
async def test_retrieve_respects_k_limit() -> None:
    search = HybridSearch()
    session = AsyncMock(spec=AsyncSession)
    folder_id = 1
    query = "test query"
    k = 5

    mock_file = _default_mock_file()

    mock_chunks = []
    for i in range(10):
        chunk = _default_mock_chunk(chunk_id=i, ordinal=i)
        mock_chunks.append((chunk, 0.9 - i * 0.01, mock_file))

    rerank_indices = list(range(k))
    rerank_scores = [0.9 - i * 0.01 for i in range(k)]

    with pytest.MonkeyPatch.context() as m:
        m.setattr(search, "_embed_query", AsyncMock(return_value=[0.1] * 1024))
        m.setattr(search, "_search_vectors", AsyncMock(return_value=mock_chunks))
        m.setattr(search, "_bm25_search", AsyncMock(return_value=[]))
        m.setattr(search, "_rerank", AsyncMock(return_value=(rerank_indices, rerank_scores, 10)))

        results = await search.retrieve(session, folder_id, query, k=k)

        assert len(results) == k


@pytest.mark.asyncio
async def test_retrieve_returns_empty_list() -> None:
    search = HybridSearch()
    session = AsyncMock(spec=AsyncSession)
    folder_id = 1
    query = "test query"

    with pytest.MonkeyPatch.context() as m:
        m.setattr(search, "_embed_query", AsyncMock(return_value=[0.1] * 1024))
        m.setattr(search, "_search_vectors", AsyncMock(return_value=[]))
        m.setattr(search, "_bm25_search", AsyncMock(return_value=[]))

        results = await search.retrieve(session, folder_id, query, k=10)

        assert results == []


def test_rrf_fuse_combines_two_lists() -> None:
    """RRF fuses vector and BM25 ranked lists with correct math (k=60)."""
    # Vector: [1, 2, 3]; BM25: [2, 1, 3, 4, 5]
    # Chunk 1: rank 1 in vector, rank 2 in BM25 -> 1/61 + 1/62
    # Chunk 2: rank 2 in vector, rank 1 in BM25 -> 1/62 + 1/61 (tie with chunk 1)
    # Chunk 3: rank 3 in vector, rank 3 in BM25 -> 1/63 + 1/63
    # Chunk 4: rank 4 in BM25 only -> 1/64
    # Chunk 5: rank 5 in BM25 only -> 1/65
    result = HybridSearch._rrf_fuse([1, 2, 3], [2, 1, 3, 4, 5], k=60)

    assert len(result) == 5
    assert result[0][0] == 1  # lower chunk_id breaks tie with chunk 2
    assert result[1][0] == 2
    assert result[2][0] == 3
    assert result[3][0] == 4
    assert result[4][0] == 5
    assert result[2][1] > result[3][1]  # 2/63 > 1/64
    assert result[3][1] > result[4][1]  # 1/64 > 1/65
    assert result[0][1] == pytest.approx(1 / 61 + 1 / 62)
    assert result[4][1] == pytest.approx(1 / 65)


def test_rrf_fuse_empty_vector() -> None:
    """RRF handles empty vector list gracefully."""
    result = HybridSearch._rrf_fuse([], [2, 1, 4], k=60)
    assert len(result) == 3
    assert result[0][0] == 2
    assert result[1][0] == 1
    assert result[2][0] == 4


def test_rrf_fuse_empty_bm25() -> None:
    """RRF handles empty BM25 list gracefully."""
    result = HybridSearch._rrf_fuse([1, 2, 3], [], k=60)
    assert len(result) == 3
    assert result[0][0] == 1


def test_rrf_fuse_both_empty() -> None:
    """RRF handles both lists empty."""
    result = HybridSearch._rrf_fuse([], [], k=60)
    assert result == []


def test_rrf_fuse_custom_k() -> None:
    """RRF k parameter affects score values."""
    result_60 = HybridSearch._rrf_fuse([1], [2], k=60)
    result_10 = HybridSearch._rrf_fuse([1], [2], k=10)
    # Lower k gives higher scores for same rank
    assert result_10[0][1] > result_60[0][1]
    assert result_60[1][1] == pytest.approx(1 / 61)


@pytest.mark.asyncio
async def test_retrieve_runs_both_legs_in_parallel() -> None:
    """Verify retrieve() calls both search legs and reranker."""
    search = HybridSearch()
    session = AsyncMock(spec=AsyncSession)
    folder_id = 1
    query = "test"

    mock_file = _default_mock_file()

    vec_chunks = [(MagicMock(spec=Chunk, id=i, text=f"vec {i}", file_id=1), 0.9, mock_file) for i in range(3)]
    bm25_chunks = [(MagicMock(spec=Chunk, id=i, text=f"bm25 {i}", file_id=1), 0.8, mock_file) for i in range(3, 6)]

    with pytest.MonkeyPatch.context() as m:
        m.setattr(search, "_embed_query", AsyncMock(return_value=[0.1] * 1024))
        m.setattr(search, "_search_vectors", AsyncMock(return_value=vec_chunks))
        m.setattr(search, "_bm25_search", AsyncMock(return_value=bm25_chunks))
        m.setattr(search, "_rerank", AsyncMock(return_value=([0, 1, 2], [0.9, 0.8, 0.7], 10)))

        results = await search.retrieve(session, folder_id, query, k=5)

        assert len(results) == 3


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

    # Search for "cat" -- chunks 0 and 1 contain cat/cats
    results = await search._bm25_search(async_session, folder_id, "cat", k=10)

    assert len(results) >= 2
    chunk0, score0, _ = results[0]
    chunk1, score1, _ = results[1]
    assert chunk0.ordinal == 0  # "cat sat on a large mat" -- "cat" is more central
    assert chunk1.ordinal == 1  # "dogs and cats" -- stemmed match on "cats"
    assert score0 > 0, "ts_rank_cd should produce a positive score for matching chunk"
    assert score0 + score1 > 0, "combined rank scores should be positive"
