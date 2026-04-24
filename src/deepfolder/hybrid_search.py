from typing import Any

from sqlalchemy import Float, and_, cast, func, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.citation_builder import Citation, CitationBuilder
from deepfolder.config import settings
from deepfolder.embedding_client import EmbeddingClient
from deepfolder.models.chunk import Chunk
from deepfolder.models.file import File


class HybridSearch:
    def __init__(self) -> None:
        self.embedding_client = EmbeddingClient(api_key=settings.voyage_api_key)

    async def retrieve(
        self, session: AsyncSession, folder_id: int, query: str, k: int = 10
    ) -> list[tuple[Chunk, float, Citation]]:
        """Vector-only top-K retrieval for v0.1.

        Args:
            session: Database session
            folder_id: Folder ID to search within
            query: Query text to embed and search
            k: Number of results to return

        Returns:
            List of (Chunk, similarity_score, Citation) tuples
        """
        query_embedding = await self._embed_query(query)
        chunks_with_files = await self._search_vectors(session, folder_id, query_embedding, k)

        results = []
        for chunk, score, file in chunks_with_files[:k]:
            citation = CitationBuilder.build(chunk, file.name)
            results.append((chunk, score, citation))

        return results

    async def _embed_query(self, query: str) -> list[float]:
        """Embed the query text."""
        embeddings = await self.embedding_client.embed_chunks([query])
        return embeddings[0]

    async def _search_vectors(
        self, session: AsyncSession, folder_id: int, query_embedding: list[float], k: int
    ) -> list[tuple[Chunk, float, File]]:
        """Search for chunks with similar embeddings using vector cosine similarity.

        Returns tuples of (Chunk, cosine_similarity_score, File).
        Note: Uses 1 - (cosine_distance) to convert pgvector distance to similarity.
        """
        query_vector: Any = cast(query_embedding, ARRAY(Float))

        result: Any = await session.execute(
            select(
                Chunk,
                (1 - (Chunk.embedding.op("<->", return_type=Float)(query_vector))).label("similarity"),
                File,
            )
            .join(File, Chunk.file_id == File.id)
            .where(
                and_(
                    File.folder_id == folder_id,
                    Chunk.embedding.isnot(None),
                )
            )
            .order_by(text("similarity DESC"))
            .limit(k)
        )

        chunks_with_files: list[tuple[Chunk, float, File]] = result.all()
        return chunks_with_files

    async def _bm25_search(
        self, session: AsyncSession, folder_id: int, query: str, k: int
    ) -> list[tuple[Chunk, float, File]]:
        """BM25 keyword search using PostgreSQL full-text search (ts_rank_cd).

        Returns tuples of (Chunk, ts_rank_cd_score, File).
        """
        ts_query = func.plainto_tsquery("english", query)

        result: Any = await session.execute(
            select(
                Chunk,
                func.ts_rank_cd(Chunk.search_vector, ts_query).label("rank"),
                File,
            )
            .join(File, Chunk.file_id == File.id)
            .where(
                and_(
                    File.folder_id == folder_id,
                    Chunk.search_vector.op("@@")(ts_query),
                )
            )
            .order_by(text("rank DESC"))
            .limit(k)
        )

        chunks_with_files: list[tuple[Chunk, float, File]] = result.all()
        return chunks_with_files
