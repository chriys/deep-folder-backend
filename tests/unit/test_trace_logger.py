from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.models.trace import Trace
from deepfolder.trace_logger import TraceLogger


@pytest.fixture
def session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def logger(session):
    return TraceLogger(session)


@pytest.mark.asyncio
async def test_record_creates_trace_row(logger, session):
    await logger.record(
        conversation_id=1,
        message_id=2,
        event_type="orchestrator_call",
        latency_ms=1500,
        prompt_tokens=500,
        completion_tokens=200,
    )

    session.add.assert_called_once()
    trace = session.add.call_args[0][0]
    assert isinstance(trace, Trace)
    assert trace.conversation_id == 1
    assert trace.message_id == 2
    assert trace.event_type == "orchestrator_call"
    assert trace.latency_ms == 1500
    assert trace.prompt_tokens == 500
    assert trace.completion_tokens == 200
    assert trace.tool_name is None
    assert trace.input is None
    assert trace.output is None


@pytest.mark.asyncio
async def test_record_tool_call(logger, session):
    await logger.record(
        conversation_id=1,
        message_id=2,
        event_type="tool_call",
        tool_name="search_docs",
        input={"query": "hello"},
        output={"result": "world"},
        latency_ms=800,
        prompt_tokens=100,
        completion_tokens=50,
    )

    trace = session.add.call_args[0][0]
    assert isinstance(trace, Trace)
    assert trace.event_type == "tool_call"
    assert trace.tool_name == "search_docs"
    assert trace.input == {"query": "hello"}
    assert trace.output == {"result": "world"}
    assert trace.latency_ms == 800
    assert trace.prompt_tokens == 100
    assert trace.completion_tokens == 50


@pytest.mark.asyncio
async def test_record_minimal(logger, session):
    await logger.record(
        conversation_id=1,
        message_id=2,
        event_type="orchestrator_call",
    )

    trace = session.add.call_args[0][0]
    assert trace.conversation_id == 1
    assert trace.message_id == 2
    assert trace.event_type == "orchestrator_call"
    assert trace.tool_name is None
    assert trace.input is None
    assert trace.output is None
    assert trace.latency_ms is None
    assert trace.prompt_tokens is None
    assert trace.completion_tokens is None
