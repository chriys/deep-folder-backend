"""Traces replay: run agent, read traces, replay with deterministic seed.

These tests verify that the orchestrator writes trace rows correctly, and
that replaying the same input against a deterministic mock produces a
structurally identical tool sequence.
"""
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.models.conversation import Conversation, Message
from deepfolder.models.folder import Folder
from deepfolder.models.trace import Trace
from deepfolder.services.agent_orchestrator import AgentOrchestrator


@pytest.fixture
def llm() -> MagicMock:
    mock = MagicMock()
    mock.generate_with_tools = AsyncMock()
    return mock


@pytest.fixture
def session() -> AsyncMock:
    mock = AsyncMock(spec=AsyncSession)
    mock.add = MagicMock()
    mock.commit = AsyncMock()
    mock.refresh = AsyncMock()
    return mock


@pytest.fixture
def tracker() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def conversation() -> MagicMock:
    conv = MagicMock(spec=Conversation)
    conv.id = 1
    conv.folder_id = 1
    return conv


@pytest.fixture
def message() -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.id = 1
    msg.content = "What does the document say about Q3?"
    return msg


@pytest.fixture
def folder() -> MagicMock:
    f = MagicMock(spec=Folder)
    f.id = 1
    return f


@pytest.fixture
def orchestrator(llm: MagicMock, tracker: AsyncMock) -> AgentOrchestrator:
    return AgentOrchestrator(llm=llm, usage_tracker=tracker)


def _parse_trace_calls(session: AsyncMock) -> list[dict[str, Any]]:
    """Extract trace records from session.add calls."""
    traces: list[dict[str, Any]] = []
    for call_args in session.add.call_args_list:
        obj = call_args[0][0]
        if isinstance(obj, Trace):
            traces.append({
                "event_type": obj.event_type,
                "tool_name": obj.tool_name,
                "input": obj.input,
                "output": obj.output,
                "latency_ms": obj.latency_ms,
            })
    return traces


async def _collect(
    orchestrator: AgentOrchestrator,
    session: AsyncSession,
    conversation: Conversation,
    message: Message,
    folder: Folder | None,
) -> list[str]:
    events: list[str] = []
    async for event_str in orchestrator.run(
        session=session,
        conversation=conversation,
        message=message,
        folder=folder,
    ):
        events.append(event_str)
    return events


class TestTracesRecording:
    """Verify trace rows are written correctly during orchestrator runs."""

    async def test_records_orchestrator_call_trace(
        self,
        orchestrator: AgentOrchestrator,
        session: AsyncMock,
        conversation: MagicMock,
        message: MagicMock,
        folder: MagicMock,
        llm: MagicMock,
    ) -> None:
        llm.generate_with_tools.return_value = ("Q3 revenue was $10M.", None, 10, 5)

        await _collect(orchestrator, session, conversation, message, folder)

        traces = _parse_trace_calls(session)
        orch_traces = [t for t in traces if t["event_type"] == "orchestrator_call"]
        assert len(orch_traces) == 1
        assert orch_traces[0]["input"] == {"query": "What does the document say about Q3?"}

    async def test_records_tool_call_traces(
        self,
        orchestrator: AgentOrchestrator,
        session: AsyncMock,
        conversation: MagicMock,
        message: MagicMock,
        folder: MagicMock,
        llm: MagicMock,
    ) -> None:
        tool_call: dict[str, Any] = {
            "id": "call_abc",
            "type": "function",
            "function": {"name": "search", "arguments": '{"query": "Q3 revenue"}'},
        }
        llm.generate_with_tools.side_effect = [
            (None, [tool_call], 15, 5),
            ("Based on search, Q3 revenue was $10M.", None, 10, 3),
        ]

        await _collect(orchestrator, session, conversation, message, folder)

        traces = _parse_trace_calls(session)
        tool_traces = [t for t in traces if t["event_type"] == "tool_call"]
        assert len(tool_traces) == 1
        assert tool_traces[0]["tool_name"] == "search"
        assert tool_traces[0]["input"] == {"query": "Q3 revenue"}
        assert tool_traces[0]["latency_ms"] is not None

    async def test_replay_produces_same_tool_sequence(
        self,
        orchestrator: AgentOrchestrator,
        session: AsyncMock,
        conversation: MagicMock,
        message: MagicMock,
        folder: MagicMock,
        llm: MagicMock,
    ) -> None:
        """Replay with deterministic seed: same input produces same tool sequence."""
        tool_call: dict[str, Any] = {
            "id": "call_replay",
            "type": "function",
            "function": {"name": "search", "arguments": '{"query": "Q3 revenue"}'},
        }
        llm.generate_with_tools.side_effect = [
            (None, [tool_call], 15, 5),
            ("Based on search, Q3 revenue was $10M.", None, 10, 3),
        ]

        # First run
        await _collect(orchestrator, session, conversation, message, folder)
        traces1 = _parse_trace_calls(session)
        tool_traces1 = [t for t in traces1 if t["event_type"] == "tool_call"]
        tool_seq1 = [(t["tool_name"], t["input"]) for t in tool_traces1]

        # Reset mocks for replay
        llm.generate_with_tools.side_effect = [
            (None, [tool_call], 15, 5),
            ("Based on search, Q3 revenue was $10M.", None, 10, 3),
        ]
        session.add.reset_mock()
        session.commit.reset_mock()

        # Second run (replay)
        await _collect(orchestrator, session, conversation, message, folder)
        traces2 = _parse_trace_calls(session)
        tool_traces2 = [t for t in traces2 if t["event_type"] == "tool_call"]
        tool_seq2 = [(t["tool_name"], t["input"]) for t in tool_traces2]

        # Both runs produce identical tool sequence
        assert tool_seq1 == tool_seq2

    async def test_trace_latency_is_positive(
        self,
        orchestrator: AgentOrchestrator,
        session: AsyncMock,
        conversation: MagicMock,
        message: MagicMock,
        folder: MagicMock,
        llm: MagicMock,
    ) -> None:
        tool_call: dict[str, Any] = {
            "id": "call_abc",
            "type": "function",
            "function": {"name": "search", "arguments": '{"query": "Q3"}'},
        }
        llm.generate_with_tools.side_effect = [
            (None, [tool_call], 15, 5),
            ("Answer.", None, 10, 3),
        ]

        await _collect(orchestrator, session, conversation, message, folder)

        traces = _parse_trace_calls(session)
        tool_traces = [t for t in traces if t["event_type"] == "tool_call"]
        for tt in tool_traces:
            assert tt["latency_ms"] > 0, "Expected positive latency_ms"
