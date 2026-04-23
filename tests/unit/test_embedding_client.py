import json
from unittest.mock import AsyncMock, patch
import pytest
import httpx

from deepfolder.embedding_client import EmbeddingClient


@pytest.fixture
def embedding_client() -> EmbeddingClient:
    return EmbeddingClient(api_key="test-api-key")


@pytest.mark.asyncio
async def test_embed_chunks_single_batch(embedding_client: EmbeddingClient) -> None:
    texts = ["Hello world", "Goodbye world"]

    mock_response = {
        "data": [
            {"embedding": [0.1, 0.2, 0.3] * 341 + [0.1]},
            {"embedding": [0.4, 0.5, 0.6] * 341 + [0.4]},
        ],
        "usage": {"total_tokens": 10},
    }

    with patch.object(embedding_client, "_call_voyage_api", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_response

        result, total_tokens = await embedding_client.embed_chunks(texts)

        assert len(result) == 2
        assert len(result[0]) == 1024
        assert len(result[1]) == 1024
        assert total_tokens == 10
        mock_call.assert_called_once()


@pytest.mark.asyncio
async def test_embed_chunks_multiple_batches(embedding_client: EmbeddingClient) -> None:
    texts = [f"Text {i}" for i in range(256)]

    mock_response = {
        "data": [
            {"embedding": [0.1] * 1024}
            for _ in range(128)
        ],
        "usage": {"total_tokens": 50},
    }

    with patch.object(embedding_client, "_call_voyage_api", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_response

        result, total_tokens = await embedding_client.embed_chunks(texts)

        assert len(result) == 256
        assert total_tokens == 100
        assert mock_call.call_count == 2


@pytest.mark.asyncio
async def test_embed_chunks_respects_batch_size(embedding_client: EmbeddingClient) -> None:
    texts = [f"Text {i}" for i in range(300)]

    with patch.object(embedding_client, "_call_voyage_api", new_callable=AsyncMock) as mock_call:

        async def mock_api(batch: list[str]) -> dict:
            return {"data": [{"embedding": [0.1] * 1024} for _ in range(len(batch))], "usage": {"total_tokens": len(batch)}}

        mock_call.side_effect = mock_api

        result, _ = await embedding_client.embed_chunks(texts)

        assert len(result) == 300
        assert mock_call.call_count == 3

        calls = mock_call.call_args_list
        assert len(calls[0][0][0]) == 128
        assert len(calls[1][0][0]) == 128
        assert len(calls[2][0][0]) == 44


@pytest.mark.asyncio
async def test_embed_chunks_empty_list(embedding_client: EmbeddingClient) -> None:
    result, total_tokens = await embedding_client.embed_chunks([])
    assert result == []
    assert total_tokens == 0


@pytest.mark.asyncio
async def test_embed_chunks_retry_on_429(embedding_client: EmbeddingClient) -> None:
    texts = ["Hello world"]

    success_body = json.dumps({"data": [{"embedding": [0.1] * 1024}], "usage": {"total_tokens": 5}}).encode()

    call_count = 0

    async def mock_post(*args: object, **kwargs: object) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, request=httpx.Request("POST", "https://example.com"))
        return httpx.Response(200, content=success_body, request=httpx.Request("POST", "https://example.com"))

    with patch.object(httpx.AsyncClient, "post", new=mock_post):
        result, total_tokens = await embedding_client.embed_chunks(texts)

        assert len(result) == 1
        assert total_tokens == 5
        assert call_count == 2
