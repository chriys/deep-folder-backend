from typing import Literal, cast

from deepfolder.llm_client import LLMClient

RouterLabel = Literal["simple", "complex", "task"]


class QueryRouter:
    """Nano classifier that labels each query as simple, complex, or task."""

    SYSTEM_PROMPT = (
        "Classify the following user query about their documents into exactly one category:\n"
        "- simple: Direct factual question answerable from retrieved context in one response\n"
        "- complex: Multi-step, analytical, comparison, or reasoning question\n"
        "- task: User wants to perform an action (create, delete, modify, send, etc.)\n\n"
        "Reply with only the category name: simple, complex, or task."
    )

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def classify(self, query: str) -> RouterLabel:
        content, _, _ = await self.llm.generate(self.SYSTEM_PROMPT, query)
        cleaned = content.strip().lower()
        if cleaned in ("simple", "complex", "task"):
            return cast(RouterLabel, cleaned)
        return "simple"
