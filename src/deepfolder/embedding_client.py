import asyncio
from typing import Any

import httpx
from deepfolder.config import settings


class EmbeddingClient:
    BATCH_SIZE = 128
    VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
    VOYAGE_RERANK_URL = "https://api.voyageai.com/v1/rerank"
    MAX_RETRIES = 5

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def embed_chunks(self, texts: list[str]) -> tuple[list[list[float]], int]:
        if not texts:
            return [], 0

        embeddings = []
        total_tokens = 0
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            response = await self._call_voyage_api(batch)
            embeddings.extend([item["embedding"] for item in response["data"]])
            total_tokens += response.get("usage", {}).get("total_tokens", 0)

        return embeddings, total_tokens

    async def rerank(
        self, query: str, documents: list[str], top_k: int = 10
    ) -> tuple[list[int], list[float], int]:
        """Rerank documents by query using Voyage cross-encoder.

        Returns (indices, relevance_scores, total_tokens) where indices map to
        positions in the input documents list, sorted by relevance DESC.
        """
        if not documents:
            return [], [], 0

        response = await self._call_voyage_rerank_api(query, documents, min(top_k, len(documents)))
        results = response.get("results", [])
        indices = [r["index"] for r in results]
        scores = [r["relevance_score"] for r in results]
        total_tokens = response.get("usage", {}).get("total_tokens", 0)
        return indices, scores, total_tokens

    async def _call_voyage_rerank_api(self, query: str, documents: list[str], top_k: int) -> dict[str, Any]:
        for attempt in range(self.MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(
                        self.VOYAGE_RERANK_URL,
                        json={
                            "model": settings.reranker_model,
                            "query": query,
                            "documents": documents,
                            "top_k": top_k,
                        },
                        headers={"Authorization": f"Bearer {self.api_key}"},
                    )
                    if response.status_code in (429, 500, 502, 503, 504):
                        if attempt < self.MAX_RETRIES - 1:
                            retry_after = response.headers.get("Retry-After", "1")
                            try:
                                wait_seconds = float(retry_after)
                            except ValueError:
                                wait_seconds = float(1**attempt)
                            await asyncio.sleep(wait_seconds)
                            continue
                    response.raise_for_status()
                    return response.json()  # type: ignore[no-any-return]
            except httpx.RequestError:
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(float(2**attempt))
                    continue
                raise
        raise RuntimeError(f"Failed to call Voyage API after {self.MAX_RETRIES} attempts")

    async def _call_voyage_api(self, texts: list[str]) -> dict[str, Any]:
        for attempt in range(self.MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(
                        self.VOYAGE_URL,
                        json={
                            "input": texts,
                            "model": settings.embedding_model,
                        },
                        headers={"Authorization": f"Bearer {self.api_key}"},
                    )
                    if response.status_code in (429, 500, 502, 503, 504):
                        if attempt < self.MAX_RETRIES - 1:
                            retry_after = response.headers.get("Retry-After", "1")
                            try:
                                wait_seconds = float(retry_after)
                            except ValueError:
                                wait_seconds = float(1 ** attempt)
                            await asyncio.sleep(wait_seconds)
                            continue
                    response.raise_for_status()
                    return response.json()  # type: ignore[no-any-return]
            except httpx.RequestError:
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(float(2 ** attempt))
                    continue
                raise
        raise RuntimeError(f"Failed to call Voyage API after {self.MAX_RETRIES} attempts")
