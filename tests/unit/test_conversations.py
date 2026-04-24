import json
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.auth.dependencies import require_user
from deepfolder.citation_builder import Citation, PrimaryUnit
from deepfolder.db import get_session
from deepfolder.main import create_app
from deepfolder.models.user import User
from deepfolder.usage_tracker import SpendCapExceeded


def _parse_sse(text: str) -> list[dict]:
    """Parse SSE event stream text into a list of {event, data} dicts."""
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_type = None
        data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if event_type and data is not None:
            events.append({"event": event_type, "data": data})
    return events


async def _create_mock_session() -> AsyncGenerator[AsyncSession, None]:
    session = AsyncMock(spec=AsyncSession)
    yield session


@pytest.fixture
def app():
    application = create_app()
    application.dependency_overrides[get_session] = _create_mock_session
    return application


def _override_user() -> User:
    user = MagicMock(spec=User)
    user.id = 1
    user.email = "test@example.com"
    return user


def _override_session(return_conversation: MagicMock | None = None):
    """Set up a session mock with optional conversation return value."""
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none.return_value = return_conversation
    result.scalar.return_value = 0.0
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.commit = AsyncMock()

    async def refresh_side_effect(obj):
        if hasattr(obj, "id") and obj.id is None:
            obj.id = 100

    session.refresh = AsyncMock(side_effect=refresh_side_effect)
    return session


def _setup_auth(app):
    """Set up auth override for authenticated tests."""
    app.dependency_overrides[require_user] = _override_user


def _make_mock_llm(router_label: str = "simple"):
    """Create a mock LLMClient that classifies as router_label and streams a canned response."""
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=(router_label, 5, 0))
    mock_llm.generate_with_tools = AsyncMock(
        return_value=("Based on the document, the answer is X.", None, 10, 5)
    )

    async def mock_stream(system_prompt, user_prompt):
        yield "Based on the document, the answer is X."

    mock_llm.generate_stream = mock_stream
    return mock_llm


def _make_mock_chunk():
    chunk = MagicMock()
    chunk.id = 1
    chunk.text = "test chunk text"
    chunk.file_id = 1
    chunk.deep_link = "https://example.com"
    chunk.primary_unit_type = "pdf_page"
    chunk.primary_unit_value = "1"
    return chunk


def _make_mock_citation():
    return Citation(
        chunk_id=1,
        file_id=1,
        file_name="test.pdf",
        primary_unit=PrimaryUnit(type="pdf_page", value="1"),
        quote="test chunk text",
        deep_link="https://example.com",
    )


@pytest.mark.asyncio
async def test_create_conversation_requires_auth(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/conversations",
            json={"folder_id": 1},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_conversations_requires_auth(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/conversations")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_conversation_requires_auth(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/conversations/1")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delete_conversation_requires_auth(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.delete("/conversations/1")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_send_message_requires_auth(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/conversations/1/messages",
            json={"content": "hello"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_send_message_returns_404_for_nonexistent_conversation(app):
    _setup_auth(app)
    session = _override_session(return_conversation=None)

    async def _get_session():
        yield session

    app.dependency_overrides[get_session] = _get_session

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/conversations/999/messages",
            json={"content": "hello"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_send_message_success(app):
    _setup_auth(app)

    mock_conv = MagicMock()
    mock_conv.id = 1
    mock_conv.folder_id = 1
    mock_conv.user_id = 1

    session = _override_session(return_conversation=mock_conv)

    async def _get_session():
        yield session

    app.dependency_overrides[get_session] = _get_session

    mock_chunk = _make_mock_chunk()
    mock_citation = _make_mock_citation()

    mock_search_instance = MagicMock()
    mock_search_instance.retrieve = AsyncMock(
        return_value=[(mock_chunk, 0.95, mock_citation)]
    )

    mock_llm = _make_mock_llm(router_label="simple")

    with (
        patch("deepfolder.api.conversations.HybridSearch", return_value=mock_search_instance),
        patch("deepfolder.api.conversations.LLMClient", return_value=mock_llm),
        patch("deepfolder.api.conversations.UsageTracker") as mock_tracker_cls,
    ):
        mock_tracker = AsyncMock()
        mock_tracker_cls.return_value = mock_tracker
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/conversations/{mock_conv.id}/messages",
                json={"content": "What does the document say?"},
            )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    events = _parse_sse(response.text)
    assert len(events) == 3
    assert events[0]["event"] == "citation"
    assert events[0]["data"]["citation"]["chunk_id"] == 1
    assert events[0]["data"]["citation"]["file_name"] == "test.pdf"
    assert events[1]["event"] == "text_delta"
    assert events[1]["data"]["delta"] == "Based on the document, the answer is X."
    assert events[2]["event"] == "done"
    assert events[2]["data"]["message_id"] == 100


@pytest.mark.asyncio
async def test_send_message_empty_citations_when_no_chunks_found(app):
    _setup_auth(app)

    mock_conv = MagicMock()
    mock_conv.id = 1
    mock_conv.folder_id = 1
    mock_conv.user_id = 1

    session = _override_session(return_conversation=mock_conv)

    async def _get_session():
        yield session

    app.dependency_overrides[get_session] = _get_session

    mock_search_instance = MagicMock()
    mock_search_instance.retrieve = AsyncMock(return_value=[])

    mock_llm = _make_mock_llm(router_label="simple")

    with (
        patch("deepfolder.api.conversations.HybridSearch", return_value=mock_search_instance),
        patch("deepfolder.api.conversations.LLMClient", return_value=mock_llm),
        patch("deepfolder.api.conversations.UsageTracker") as mock_tracker_cls,
    ):
        mock_tracker = AsyncMock()
        mock_tracker_cls.return_value = mock_tracker
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/conversations/{mock_conv.id}/messages",
                json={"content": "What about this?"},
            )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert len(events) == 2
    assert events[0]["event"] == "text_delta"
    assert events[1]["event"] == "done"


@pytest.mark.asyncio
async def test_send_message_returns_429_when_spend_cap_exceeded(app):
    _setup_auth(app)

    mock_conv = MagicMock()
    mock_conv.id = 1
    mock_conv.folder_id = 1
    mock_conv.user_id = 1

    session = _override_session(return_conversation=mock_conv)

    async def _get_session():
        yield session

    app.dependency_overrides[get_session] = _get_session

    mock_tracker = MagicMock()
    mock_tracker.check_spend_cap = AsyncMock(side_effect=SpendCapExceeded("Cap exceeded"))

    with patch("deepfolder.api.conversations.UsageTracker", return_value=mock_tracker):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/conversations/{mock_conv.id}/messages",
                json={"content": "test"},
            )

    assert response.status_code == 429
    data = response.json()
    assert "Cap exceeded" in data["detail"]


@pytest.mark.asyncio
async def test_send_message_complex_returns_orchestrator_response(app):
    _setup_auth(app)

    mock_conv = MagicMock()
    mock_conv.id = 1
    mock_conv.folder_id = 1
    mock_conv.user_id = 1

    mock_fld = MagicMock()
    mock_fld.id = 1

    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none.side_effect = [mock_conv, mock_fld]
    result.scalar.return_value = 0.0
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.commit = AsyncMock()

    async def refresh_side_effect(obj):
        if hasattr(obj, "id") and obj.id is None:
            obj.id = 100

    session.refresh = AsyncMock(side_effect=refresh_side_effect)

    async def _get_session():
        yield session

    app.dependency_overrides[get_session] = _get_session

    mock_llm = _make_mock_llm(router_label="complex")

    with (
        patch("deepfolder.api.conversations.LLMClient", return_value=mock_llm),
        patch("deepfolder.api.conversations.UsageTracker") as mock_tracker_cls,
    ):
        mock_tracker = AsyncMock()
        mock_tracker_cls.return_value = mock_tracker
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/conversations/{mock_conv.id}/messages",
                json={"content": "Compare the documents"},
            )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    events = _parse_sse(response.text)
    assert len(events) >= 2
    assert events[0]["event"] == "text_delta"
    assert events[-1]["event"] == "done"


@pytest.mark.asyncio
async def test_send_message_task_returns_501(app):
    _setup_auth(app)

    mock_conv = MagicMock()
    mock_conv.id = 1
    mock_conv.folder_id = 1
    mock_conv.user_id = 1

    session = _override_session(return_conversation=mock_conv)

    async def _get_session():
        yield session

    app.dependency_overrides[get_session] = _get_session

    mock_llm = _make_mock_llm(router_label="task")

    with (
        patch("deepfolder.api.conversations.LLMClient", return_value=mock_llm),
        patch("deepfolder.api.conversations.UsageTracker") as mock_tracker_cls,
    ):
        mock_tracker = AsyncMock()
        mock_tracker_cls.return_value = mock_tracker
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/conversations/{mock_conv.id}/messages",
                json={"content": "Extract action items"},
            )

    assert response.status_code == 501
    events = _parse_sse(response.text)
    assert len(events) == 1
    assert events[0]["event"] == "error"
    assert events[0]["data"]["code"] == "not_implemented"
    assert "task" in events[0]["data"]["message"]
