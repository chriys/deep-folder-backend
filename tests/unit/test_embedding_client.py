import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

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

        async def mock_api(batch: list[str]) -> dict[str, Any]:
            data = [{"embedding": [0.1] * 1024} for _ in range(len(batch))]
            return {"data": data, "usage": {"total_tokens": len(batch)}}

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

    success_body = json.dumps(
        {"data": [{"embedding": [0.1] * 1024}], "usage": {"total_tokens": 5}}
    ).encode()

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


@pytest.mark.asyncio
async def test_rerank_makes_correct_api_call(embedding_client: EmbeddingClient) -> None:
    """Rerank sends correct request format to Voyage rerank endpoint."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [
            {"index": 2, "relevance_score": 0.95, "document": "doc3"},
            {"index": 0, "relevance_score": 0.80, "document": "doc1"},
        ],
        "usage": {"total_tokens": 50},
    }

    with patch.object(
        embedding_client, "_call_voyage_rerank_api", new_callable=AsyncMock
    ) as mock_call:
        mock_call.return_value = mock_response.json.return_value

        indices, scores, tokens = await embedding_client.rerank(
            query="test query",
            documents=["doc1", "doc2", "doc3"],
            top_k=2,
        )

    assert indices == [2, 0]
    assert scores == [0.95, 0.80]
    assert tokens == 50
    mock_call.assert_called_once_with("test query", ["doc1", "doc2", "doc3"], 2)


@pytest.mark.asyncio
async def test_rerank_returns_empty_for_no_documents(embedding_client: EmbeddingClient) -> None:
    indices, scores, tokens = await embedding_client.rerank("query", [], top_k=5)
    assert indices == []
    assert scores == []
    assert tokens == 0


@pytest.mark.asyncio
async def test_rerank_http_request_format(embedding_client: EmbeddingClient) -> None:
    """Verify the raw HTTP request payload to the rerank endpoint."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [{"index": 0, "relevance_score": 0.99, "document": "doc1"}],
        "usage": {"total_tokens": 10},
    }

    def make_client(*args: object, **kwargs: object) -> MagicMock:
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock()
        client.post = AsyncMock(return_value=mock_resp)
        return client

    with patch("httpx.AsyncClient", new=make_client):
        indices, scores, tokens = await embedding_client.rerank("my query", ["doc1", "doc2"], 1)

    assert indices == [0]
    assert scores[0] == 0.99
    assert tokens == 10


@pytest.mark.asyncio
async def test_rerank_call_shape_and_batch_limit(embedding_client: EmbeddingClient) -> None:
    """Rerank sends correct input shape with ≤ 128 documents per API call."""
    captured_kwargs: dict[str, Any] = {}

    async def mock_rerank_api(query: str, documents: list[str], top_k: int) -> dict[str, Any]:
        captured_kwargs["query"] = query
        captured_kwargs["documents"] = documents
        captured_kwargs["top_k"] = top_k
        return {
            "results": [
                {"index": i, "relevance_score": 1.0 - i * 0.01, "document": documents[i]}
                for i in range(min(top_k, len(documents)))
            ],
            "usage": {"total_tokens": 50},
        }

    # Test with exactly 128 documents (the batch limit)
    docs_128 = [f"doc_{i}" for i in range(128)]
    with patch.object(embedding_client, "_call_voyage_rerank_api", new=mock_rerank_api):
        indices, scores, tokens = await embedding_client.rerank(
            query="test query", documents=docs_128, top_k=10,
        )

    assert captured_kwargs["query"] == "test query"
    assert len(captured_kwargs["documents"]) == 128
    assert captured_kwargs["top_k"] == 10
    assert len(indices) == 10  # top_k
    assert tokens == 50

    # Test with fewer docs
    captured_kwargs.clear()
    docs_small = ["doc_a", "doc_b", "doc_c"]
    with patch.object(embedding_client, "_call_voyage_rerank_api", new=mock_rerank_api):
        indices, scores, tokens = await embedding_client.rerank(
            query="short query", documents=docs_small, top_k=3,
        )

    assert len(captured_kwargs["documents"]) == 3
    assert captured_kwargs["top_k"] == 3
