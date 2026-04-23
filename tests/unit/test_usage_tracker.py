from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.usage_tracker import UsageTracker, SpendCapExceeded
from deepfolder.models.usage import Usage


@pytest.fixture
def session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def tracker(session):
    return UsageTracker(session, user_id=1)


@pytest.mark.asyncio
async def test_record_creates_usage_row(tracker, session):
    await tracker.record("llm", "deepseek-chat", input_tokens=100, output_tokens=50)

    session.add.assert_called_once()
    call_args = session.add.call_args[0][0]
    assert isinstance(call_args, Usage)
    assert call_args.kind == "llm"
    assert call_args.model == "deepseek-chat"
    assert call_args.input_tokens == 100
    assert call_args.output_tokens == 50
    assert call_args.cost_usd > 0
    assert call_args.user_id == 1


@pytest.mark.asyncio
async def test_record_computes_cost_llm(tracker, session):
    await tracker.record("llm", "deepseek-chat", input_tokens=1_000_000, output_tokens=500_000)

    call_args = session.add.call_args[0][0]
    # $2.00 per 1M input + $8.00 per 1M output
    expected_cost = 2.00 + 4.00  # input: 1M * $2/1M = $2, output: 0.5M * $8/1M = $4
    assert call_args.cost_usd == pytest.approx(expected_cost, rel=1e-4)


@pytest.mark.asyncio
async def test_record_computes_cost_embedding(tracker, session):
    await tracker.record("embedding", "voyage-4", input_tokens=100_000, output_tokens=0)

    call_args = session.add.call_args[0][0]
    # $0.10 per 1M input tokens, output_tokens ignored
    expected_cost = 0.01  # 100k / 1M * $0.10
    assert call_args.cost_usd == pytest.approx(expected_cost, rel=1e-4)


@pytest.mark.asyncio
async def test_record_with_unknown_model(tracker, session):
    await tracker.record("llm", "unknown-model", input_tokens=100, output_tokens=50)

    call_args = session.add.call_args[0][0]
    assert call_args.cost_usd == 0.0


@pytest.mark.asyncio
async def test_check_spend_cap_does_not_raise_when_under_limit(tracker, session):
    result = MagicMock()
    result.scalar.return_value = 5.0
    session.execute = AsyncMock(return_value=result)

    # Should not raise
    await tracker.check_spend_cap()


@pytest.mark.asyncio
async def test_check_spend_cap_raises_when_over_limit(tracker, session):
    result = MagicMock()
    result.scalar.return_value = 15.0
    session.execute = AsyncMock(return_value=result)

    with pytest.raises(SpendCapExceeded):
        await tracker.check_spend_cap()


@pytest.mark.asyncio
async def test_check_spend_cap_handles_no_usage(tracker, session):
    result = MagicMock()
    result.scalar.return_value = None
    session.execute = AsyncMock(return_value=result)

    # Should not raise when there's no usage
    await tracker.check_spend_cap()
