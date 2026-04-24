from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.models.trace import Trace


class TraceLogger:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        conversation_id: int,
        message_id: int,
        event_type: str,
        tool_name: str | None = None,
        input: dict | None = None,
        output: dict | None = None,
        latency_ms: int | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> None:
        trace = Trace(
            conversation_id=conversation_id,
            message_id=message_id,
            event_type=event_type,
            tool_name=tool_name,
            input=input,
            output=output,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        self.session.add(trace)
