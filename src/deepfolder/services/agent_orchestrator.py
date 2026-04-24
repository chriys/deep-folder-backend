"""AgentOrchestrator stub — returns 501 until the full Tool Loop lands in v0.4."""


class AgentOrchestrator:
    """Stub placeholder for the full Agentic Tool Loop.

    Currently raises NotImplementedError to signal 501 to the caller.
    """

    async def run(self, conversation_id: int, query: str) -> None:
        raise NotImplementedError("Agent orchestration not yet implemented (v0.4)")
