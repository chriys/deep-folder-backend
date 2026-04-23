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
        ]
    }

    with patch.object(embedding_client, "_call_voyage_api", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_response

        result = await embedding_client.embed_chunks(texts)

        assert len(result) == 2
        assert len(result[0]) == 1024
        assert len(result[1]) == 1024
        mock_call.assert_called_once()


@pytest.mark.asyncio
async def test_embed_chunks_multiple_batches(embedding_client: EmbeddingClient) -> None:
    texts = [f"Text {i}" for i in range(256)]

    mock_response = {
        "data": [
            {"embedding": [0.1] * 1024}
            for _ in range(128)
        ]
    }

    with patch.object(embedding_client, "_call_voyage_api", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_response

        result = await embedding_client.embed_chunks(texts)

        assert len(result) == 256
        assert mock_call.call_count == 2


@pytest.mark.asyncio
async def test_embed_chunks_respects_batch_size(embedding_client: EmbeddingClient) -> None:
    texts = [f"Text {i}" for i in range(300)]

    mock_response = {
        "data": [{"embedding": [0.1] * 1024} for _ in range(128)]
    }

    with patch.object(embedding_client, "_call_voyage_api", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = mock_response

        result = await embedding_client.embed_chunks(texts)

        assert len(result) == 300
        assert mock_call.call_count == 3

        calls = mock_call.call_args_list
        assert len(calls[0][0][0]) == 128
        assert len(calls[1][0][0]) == 128
        assert len(calls[2][0][0]) == 44


@pytest.mark.asyncio
async def test_embed_chunks_empty_list(embedding_client: EmbeddingClient) -> None:
    result = await embedding_client.embed_chunks([])
    assert result == []


@pytest.mark.asyncio
async def test_embed_chunks_retry_on_429(embedding_client: EmbeddingClient) -> None:
    texts = ["Hello world"]

    success_response = {
        "data": [{"embedding": [0.1] * 1024}]
    }

    call_count = 0

    async def mock_api_call(batch: list[str]) -> dict:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.HTTPStatusError("429", request=None, response=None)
        return success_response

    with patch.object(embedding_client, "_call_voyage_api", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = mock_api_call

        result = await embedding_client.embed_chunks(texts)

        assert len(result) == 1
        assert mock_call.call_count == 2
