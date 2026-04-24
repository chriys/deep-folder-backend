import asyncio
from typing import Any

from sqlalchemy import Float, and_, cast, func, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.citation_builder import Citation, CitationBuilder
from deepfolder.config import settings
from deepfolder.embedding_client import EmbeddingClient
from deepfolder.models.chunk import Chunk
from deepfolder.models.file import File

TOP_K_LEG = 25
RRF_K = 60
RERANK_DEPTH = 50


class HybridSearch:
    def __init__(self) -> None:
        self.embedding_client = EmbeddingClient(api_key=settings.voyage_api_key)

    async def retrieve(
        self, session: AsyncSession, folder_id: int, query: str, k: int = 10
    ) -> list[tuple[Chunk, float, Citation]]:
        """Hybrid retrieval: vector + BM25 in parallel, RRF fusion, Voyage reranker."""
        query_embedding = await self._embed_query(query)

        vec_results, bm25_results = await asyncio.gather(
            self._search_vectors(session, folder_id, query_embedding, TOP_K_LEG),
            self._bm25_search(session, folder_id, query, TOP_K_LEG),
        )

        chunks_map: dict[int, Chunk] = {}
        files_map: dict[int, File] = {}
        for c, _s, f in vec_results:
            chunks_map[c.id] = c
            files_map[c.id] = f
        for c, _s, f in bm25_results:
            chunks_map[c.id] = c
            files_map.setdefault(c.id, f)

        fused = self._rrf_fuse(
            [c.id for c, _s, _f in vec_results],
            [c.id for c, _s, _f in bm25_results],
        )

        top_fused = fused[:RERANK_DEPTH]
        if top_fused:
            chunk_texts = [chunks_map[cid].text for cid, _rrf_score in top_fused]
            indices, scores, _ = await self._rerank(query, chunk_texts, k)
            reranked = [(top_fused[i][0], scores[j]) for j, i in enumerate(indices)]
        else:
            reranked = []

        results: list[tuple[Chunk, float, Citation]] = []
        for chunk_id, score in reranked:
            chunk = chunks_map[chunk_id]
            citation = CitationBuilder.build(chunk, files_map[chunk_id].name)
            results.append((chunk, score, citation))

        return results

    async def _rerank(
        self, query: str, documents: list[str], top_k: int
    ) -> tuple[list[int], list[float], int]:
        return await self.embedding_client.rerank(query, documents, top_k)

    @staticmethod
    def _rrf_fuse(
        vector_ids: list[int],
        bm25_ids: list[int],
        k: int = RRF_K,
    ) -> list[tuple[int, float]]:
        """Fuse two ranked chunk-id lists via Reciprocal Rank Fusion.

        Returns list of (chunk_id, rrf_score) sorted by score descending,
        with chunk_id as tiebreaker for determinism.
        """
        scores: dict[int, float] = {}
        for rank, cid in enumerate(vector_ids, start=1):
            scores[cid] = 1.0 / (k + rank)
        for rank, cid in enumerate(bm25_ids, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        return sorted(scores.items(), key=lambda x: (-x[1], x[0]))

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
