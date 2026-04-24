import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.models.conversation import Conversation, Message
from deepfolder.models.folder import Folder
from deepfolder.services.agent_orchestrator import (
    MAX_TOOL_CALLS,
    AgentOrchestrator,
    _sse_event,
)


def _parse_sse(text: str) -> list[dict]:
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


@pytest.fixture
def llm():
    mock = MagicMock()
    mock.generate_with_tools = AsyncMock()
    return mock


@pytest.fixture
def session():
    mock = AsyncMock(spec=AsyncSession)
    mock.add = MagicMock()
    mock.commit = AsyncMock()
    mock.refresh = AsyncMock()
    return mock


@pytest.fixture
def tracker():
    return AsyncMock()


@pytest.fixture
def conversation():
    conv = MagicMock(spec=Conversation)
    conv.id = 1
    conv.folder_id = 1
    return conv


@pytest.fixture
def message():
    msg = MagicMock(spec=Message)
    msg.id = 1
    msg.content = "What does the document say about Q3?"
    return msg


@pytest.fixture
def folder():
    f = MagicMock(spec=Folder)
    f.id = 1
    return f


@pytest.fixture
def orchestrator(llm, tracker):
    return AgentOrchestrator(llm=llm, usage_tracker=tracker)


async def _collect(orchestrator, session, conversation, message, folder):
    events = []
    async for event_str in orchestrator.run(
        session=session,
        conversation=conversation,
        message=message,
        folder=folder,
    ):
        events.append(event_str)
    return events


class TestOrchestratorDirectAnswer:
    """LLM responds with text directly, no tool calls."""

    async def test_returns_text_delta_and_done(
        self, orchestrator, session, conversation, message, folder, llm
    ):
        llm.generate_with_tools.return_value = ("Q3 revenue was $10M.", None, 10, 5)

        events = await _collect(orchestrator, session, conversation, message, folder)
        parsed = _parse_sse("".join(events))

        assert any(e["event"] == "text_delta" for e in parsed)
        assert any(e["event"] == "done" for e in parsed)
        td = [e for e in parsed if e["event"] == "text_delta"]
        assert td[0]["data"]["delta"] == "Q3 revenue was $10M."
        assert session.add.called
        session.commit.assert_called_once()

    async def test_records_usage(
        self, orchestrator, session, conversation, message, folder, llm, tracker
    ):
        llm.generate_with_tools.return_value = ("Answer.", None, 20, 10)

        await _collect(orchestrator, session, conversation, message, folder)

        tracker.record.assert_called_once_with("llm", "deepseek-chat", 20, 10)

    async def test_saves_assistant_message_with_citations_none(
        self, orchestrator, session, conversation, message, folder, llm
    ):
        llm.generate_with_tools.return_value = ("Answer.", None, 10, 5)
        await _collect(orchestrator, session, conversation, message, folder)

        added = session.add.call_args[0][0]
        assert added.role == "assistant"
        assert added.content == "Answer."
        assert added.citations is None


class TestOrchestratorToolCalls:
    """LLM makes tool calls and gets results."""

    async def test_search_tool_yields_tool_events(
        self, orchestrator, session, conversation, message, folder, llm
    ):
        tool_call = {
            "id": "call_abc",
            "type": "function",
            "function": {"name": "search", "arguments": '{"query": "Q3 revenue"}'},
        }
        llm.generate_with_tools.side_effect = [
            (None, [tool_call], 15, 5),
            ("Based on search, Q3 revenue was $10M.", None, 10, 3),
        ]

        events = await _collect(orchestrator, session, conversation, message, folder)
        parsed = _parse_sse("".join(events))

        starts = [e for e in parsed if e["event"] == "tool_call_start"]
        assert len(starts) == 1
        assert starts[0]["data"]["tool_name"] == "search"
        assert starts[0]["data"]["arguments"] == {"query": "Q3 revenue"}

        results = [e for e in parsed if e["event"] == "tool_call_result"]
        assert len(results) == 1
        assert results[0]["data"]["tool_name"] == "search"

        tds = [e for e in parsed if e["event"] == "text_delta"]
        assert len(tds) == 1
        assert "Q3 revenue" in tds[0]["data"]["delta"]

        assert any(e["event"] == "done" for e in parsed)

    async def test_multiple_tool_calls_in_one_response(
        self, orchestrator, session, conversation, message, folder, llm
    ):
        tcs = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "search", "arguments": '{"query": "Q3"}'},
            },
            {
                "id": "call_2",
                "type": "function",
                "function": {"name": "search", "arguments": '{"query": "Q4"}'},
            },
        ]
        llm.generate_with_tools.side_effect = [
            (None, tcs, 20, 10),
            ("Compared: Q3 good, Q4 better.", None, 10, 5),
        ]

        events = await _collect(orchestrator, session, conversation, message, folder)
        parsed = _parse_sse("".join(events))

        starts = [e for e in parsed if e["event"] == "tool_call_start"]
        assert len(starts) == 2

        results = [e for e in parsed if e["event"] == "tool_call_result"]
        assert len(results) == 2

        done = [e for e in parsed if e["event"] == "done"]
        assert len(done) == 1


class TestOrchestratorToolCap:
    """Hard cap of 15 tool calls."""

    async def test_error_event_when_cap_exceeded(
        self, orchestrator, session, conversation, message, folder, llm
    ):
        def generate_side_effect(messages=None, tools=None):
            tool_call = {
                "id": f"call_{hash(str(messages))}",
                "type": "function",
                "function": {"name": "search", "arguments": '{"query": "test"}'},
            }
            return (None, [tool_call], 5, 2)

        llm.generate_with_tools.side_effect = generate_side_effect

        events = await _collect(orchestrator, session, conversation, message, folder)
        parsed = _parse_sse("".join(events))

        starts = [e for e in parsed if e["event"] == "tool_call_start"]
        assert len(starts) == MAX_TOOL_CALLS

        errors = [e for e in parsed if e["event"] == "error"]
        assert len(errors) == 1
        assert errors[0]["data"]["code"] == "too_many_tool_calls"


class TestOrchestratorStubTools:
    """Stub tools return not-implemented messages."""

    @pytest.mark.parametrize("tool_name", [
        "list_file_summaries",
        "find_contradictions",
        "synthesize_themes",
        "run_task",
    ])
    async def test_stub_tool_returns_error(
        self, orchestrator, session, conversation, message, folder, llm, tool_name
    ):
        tool_call = {
            "id": "call_stub",
            "type": "function",
            "function": {"name": tool_name, "arguments": "{}"},
        }
        llm.generate_with_tools.side_effect = [
            (None, [tool_call], 5, 2),
            ("Understood.", None, 5, 2),
        ]

        events = await _collect(orchestrator, session, conversation, message, folder)
        parsed = _parse_sse("".join(events))

        results = [e for e in parsed if e["event"] == "tool_call_result"]
        assert len(results) == 1
        assert "not yet implemented" in results[0]["data"]["result"]


class TestOrchestratorErrorHandling:
    """Error handling in the tool loop."""

    async def test_internal_error_yields_error_event(
        self, orchestrator, session, conversation, message, folder, llm
    ):
        llm.generate_with_tools.side_effect = RuntimeError("API failure")

        events = await _collect(orchestrator, session, conversation, message, folder)
        event_str = "".join(events)
        parsed = _parse_sse(event_str)

        errors = [e for e in parsed if e["event"] == "error"]
        assert len(errors) >= 1
        assert errors[0]["data"]["code"] == "internal_error"

    async def test_unknown_tool_returns_error_result(
        self, orchestrator, session, conversation, message, folder, llm
    ):
        tool_call = {
            "id": "call_unknown",
            "type": "function",
            "function": {"name": "nonexistent_tool", "arguments": "{}"},
        }
        llm.generate_with_tools.side_effect = [
            (None, [tool_call], 5, 2),
            ("Done.", None, 5, 2),
        ]

        events = await _collect(orchestrator, session, conversation, message, folder)
        parsed = _parse_sse("".join(events))

        results = [e for e in parsed if e["event"] == "tool_call_result"]
        assert "Unknown tool" in results[0]["data"]["result"]


class TestSseEventHelper:
    def test_formats_sse_event(self):
        result = _sse_event("text_delta", {"delta": "hello"})
        assert result == 'event: text_delta\ndata: {"delta": "hello"}\n\n'
