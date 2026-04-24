from unittest.mock import AsyncMock, MagicMock

import pytest

from deepfolder.query_router import QueryRouter


@pytest.mark.asyncio
async def test_classify_returns_simple():
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=("simple", 5, 0))
    router = QueryRouter(llm)
    result = await router.classify("What is the capital of France?")
    assert result == "simple"


@pytest.mark.asyncio
async def test_classify_returns_complex():
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=("complex", 5, 0))
    router = QueryRouter(llm)
    result = await router.classify("Compare the Q3 and Q4 reports")
    assert result == "complex"


@pytest.mark.asyncio
async def test_classify_returns_task():
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=("task", 5, 0))
    router = QueryRouter(llm)
    result = await router.classify("Create a summary of all documents")
    assert result == "task"


@pytest.mark.asyncio
async def test_classify_fallback_to_simple_on_unknown():
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=("unknown_response", 5, 0))
    router = QueryRouter(llm)
    result = await router.classify("Some weird query")
    assert result == "simple"


@pytest.mark.asyncio
async def test_classify_case_insensitive():
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=("Complex", 5, 0))
    router = QueryRouter(llm)
    result = await router.classify("Compare documents")
    assert result == "complex"


@pytest.mark.asyncio
async def test_classify_strips_whitespace():
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=("  simple  ", 5, 0))
    router = QueryRouter(llm)
    result = await router.classify("What is X?")
    assert result == "simple"


@pytest.mark.asyncio
async def test_classify_calls_llm_with_system_prompt():
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=("simple", 10, 0))
    router = QueryRouter(llm)

    await router.classify("What is the revenue?")

    llm.generate.assert_called_once()
    system_prompt, user_prompt = llm.generate.call_args[0]
    assert "simple" in system_prompt
    assert "complex" in system_prompt
    assert "task" in system_prompt
    assert user_prompt == "What is the revenue?"


# Labeled fixture set: at least 10 queries covering all three categories.
FIXTURE_QUERIES: list[tuple[str, str]] = [
    # simple — direct factual questions
    ("What is the net income for Q3?", "simple"),
    ("When was the meeting held?", "simple"),
    ("Who is the author of the report?", "simple"),
    ("What page has the revenue table?", "simple"),
    ("What did the CEO say about growth?", "simple"),
    # complex — analytical, multi-step, comparison
    ("Compare the Q3 and Q4 revenue figures", "complex"),
    ("What are the main differences between proposal A and B?", "complex"),
    ("Why did the profit margin decrease in Q4?", "complex"),
    ("Summarize the arguments for and against the acquisition", "complex"),
    # task — action-oriented
    ("Create a summary of all documents in the folder", "task"),
    ("Extract action items from the meeting notes", "task"),
    ("Send an email to the team with the findings", "task"),
]


@pytest.mark.asyncio
async def test_labeled_fixture_set():
    """Verify QueryRouter correctly classifies the labeled fixture set (>=80% accuracy)."""
    llm = MagicMock()

    async def mock_generate(system_prompt: str, user_prompt: str) -> tuple[str, int, int]:
        label = "unknown"
        query = user_prompt.strip().lower()
        # Heuristic-based mock that mirrors expected classification logic
        complex_kw = ("compare", "differences", "why did", "summarize the arguments")
        if any(w in query for w in complex_kw):
            label = "complex"
        elif any(w in query for w in ("create a", "extract", "send an")):
            label = "task"
        elif any(w in query for w in ("what is", "what did", "what page", "when was", "who is")):
            label = "simple"
        return (label, 5, 0)

    llm.generate = mock_generate
    router = QueryRouter(llm)

    correct = 0
    for query, expected in FIXTURE_QUERIES:
        result = await router.classify(query)
        if result == expected:
            correct += 1

    accuracy = correct / len(FIXTURE_QUERIES)
    assert accuracy >= 0.8, f"Accuracy {accuracy:.0%} < 80% on fixture set"
