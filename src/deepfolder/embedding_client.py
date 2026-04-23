import asyncio
import httpx
from deepfolder.config import settings


class EmbeddingClient:
    BATCH_SIZE = 128
    VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
    MAX_RETRIES = 5

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def embed_chunks(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        embeddings = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            batch_embeddings = await self._call_voyage_api(batch)
            embeddings.extend([item["embedding"] for item in batch_embeddings["data"]])

        return embeddings

    async def _call_voyage_api(self, texts: list[str]) -> dict:
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
                    return response.json()
            except httpx.RequestError:
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(float(2 ** attempt))
                    continue
                raise
        raise RuntimeError(f"Failed to call Voyage API after {self.MAX_RETRIES} attempts")
