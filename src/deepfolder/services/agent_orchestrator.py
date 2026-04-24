import json
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.citation_builder import CitationBuilder
from deepfolder.config import settings
from deepfolder.hybrid_search import HybridSearch
from deepfolder.llm_client import LLMClient
from deepfolder.models.chunk import Chunk
from deepfolder.models.conversation import Conversation, Message
from deepfolder.models.file import File
from deepfolder.models.folder import Folder
from deepfolder.trace_logger import TraceLogger
from deepfolder.usage_tracker import UsageTracker

MAX_TOOL_CALLS = 15

SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions about the user's "
    "documents.\n\n"
    "Available tools:\n"
    "- search(query): Search documents for relevant information. "
    "Returns text chunks with [citation:X] markers.\n"
    "- list_folder(): List all files in the current folder.\n"
    "- get_file_outline(file_name): Get the section outline "
    "of a specific file.\n"
    "- read_section(file_name, primary_unit_type, primary_unit_value): "
    "Read the full text of a specific section.\n"
    "- compare(file_name_a, file_name_b): Get the contents of two "
    "files side by side for comparison.\n\n"
    "When you use information from search or compare results, cite "
    "the source by including the [citation:X] marker in your response.\n"
    "Only use citation markers that were provided in the tool results.\n"
    "Never fabricate citations. If you are unsure, do not include a "
    "citation."
)

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search documents using hybrid search "
                "(vector + keyword). Use to find relevant info "
                "to answer the user's question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_folder",
            "description": "List all files in the current folder. "
                "Use to discover what documents are available.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_outline",
            "description": "Get the outline (sections/chunks) "
                "of a specific file. Use to understand "
                "the structure of a document.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "The name of the file",
                    },
                },
                "required": ["file_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_section",
            "description": "Read the full text of a specific "
                "section/chunk in a file. Use after getting "
                "a file outline to read a specific section.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "The name of the file",
                    },
                    "primary_unit_type": {
                        "type": "string",
                        "description": "Primary unit type "
                            "(e.g., pdf_page, docs_heading, slide)",
                    },
                    "primary_unit_value": {
                        "type": "string",
                        "description": "The value/identifier of the primary unit",
                    },
                },
                "required": ["file_name", "primary_unit_type", "primary_unit_value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare",
            "description": "Get the contents of two files side by "
                "side with citation markers. Use when the user "
                "wants to compare two documents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name_a": {
                        "type": "string",
                        "description": "Name of the first file",
                    },
                    "file_name_b": {
                        "type": "string",
                        "description": "Name of the second file",
                    },
                },
                "required": ["file_name_a", "file_name_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_file_summaries",
            "description": "Get AI-generated summaries of all files in the folder.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_contradictions",
            "description": "Find contradictions across documents.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "synthesize_themes",
            "description": "Identify and synthesize common themes across documents.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_task",
            "description": "Execute a multi-step task.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]

STUB_TOOLS = frozenset({
    "list_file_summaries",
    "find_contradictions",
    "synthesize_themes",
    "run_task",
})


def _sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


class AgentOrchestrator:
    """Full Tool Loop for complex queries.

    Runs a tool-calling loop with a hard cap of 15 tool calls per
    message. Streams responses via SSE events.
    """

    def __init__(self, llm: LLMClient, usage_tracker: UsageTracker) -> None:
        self.llm = llm
        self.usage_tracker = usage_tracker

    async def run(
        self,
        session: AsyncSession,
        conversation: Conversation,
        message: Message,
        folder: Folder | None,
    ) -> AsyncGenerator[str, None]:
        """Run the tool loop and yield SSE event strings."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message.content},
        ]

        tool_call_count = 0
        full_content = ""
        all_citations: list[dict[str, Any]] = []

        trace_logger = TraceLogger(session)

        try:
            await trace_logger.record(
                conversation_id=conversation.id,
                message_id=message.id,
                event_type="orchestrator_call",
                input={"query": message.content},
            )

            while True:
                content, tool_calls, input_tokens, output_tokens = (
                    await self.llm.generate_with_tools(
                        messages=messages,
                        tools=TOOLS,
                    )
                )

                await self.usage_tracker.record(
                    "llm", settings.llm_model, input_tokens, output_tokens,
                )

                if content:
                    full_content += content
                    yield _sse_event("text_delta", {"delta": content})

                if not tool_calls:
                    break

                hit_cap = False
                for tc in tool_calls:
                    tool_call_count += 1
                    if tool_call_count > MAX_TOOL_CALLS:
                        yield _sse_event("error", {
                            "code": "too_many_tool_calls",
                            "message": "Exceeded maximum of 15 tool calls per message.",
                        })
                        hit_cap = True
                        break

                    name = tc["function"]["name"]
                    args = json.loads(tc["function"]["arguments"])

                    yield _sse_event("tool_call_start", {
                        "tool_name": name,
                        "arguments": args,
                    })

                    tool_start = time.monotonic()
                    tool_result, tool_citations = await self._execute_tool(
                        session, folder, name, args,
                    )
                    tool_latency = int((time.monotonic() - tool_start) * 1000)

                    for c in tool_citations:
                        all_citations.append(c)
                        yield _sse_event("citation", {"citation": c})

                    yield _sse_event("tool_call_result", {
                        "tool_name": name,
                        "result": tool_result,
                    })

                    await trace_logger.record(
                        conversation_id=conversation.id,
                        message_id=message.id,
                        event_type="tool_call",
                        tool_name=name,
                        input=args,
                        output={"result": tool_result[:500]},
                        latency_ms=tool_latency,
                    )

                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": tc["function"]["arguments"],
                                },
                            }
                        ],
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": tool_result,
                    })

                if hit_cap:
                    break

            assistant_msg = Message(
                conversation_id=conversation.id,
                role="assistant",
                content=full_content,
                citations=all_citations if all_citations else None,
            )
            session.add(assistant_msg)
            await session.commit()
            await session.refresh(assistant_msg)

            yield _sse_event("done", {"message_id": assistant_msg.id})

        except Exception:
            yield _sse_event("error", {
                "code": "internal_error",
                "message": "Failed to generate response",
            })

    async def _execute_tool(
        self,
        session: AsyncSession,
        folder: Folder | None,
        name: str,
        args: dict[str, Any],
    ) -> tuple[str, list[dict[str, Any]]]:
        if name in STUB_TOOLS:
            return f"Error: The tool '{name}' is not yet implemented.", []

        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return f"Error: Unknown tool '{name}'.", []

        try:
            return await handler(session, folder, **args)
        except Exception as exc:
            return f"Error executing tool '{name}': {exc}", []


async def _tool_search(
    session: AsyncSession,
    folder: Folder | None,
    query: str,
) -> tuple[str, list[dict[str, Any]]]:
    if folder is None:
        return "Error: No folder available.", []
    search = HybridSearch()
    results = await search.retrieve(session, folder.id, query, k=10)

    context_parts: list[str] = []
    citation_dicts: list[dict[str, Any]] = []

    for chunk, _score, citation in results:
        context_parts.append(f"[citation:{chunk.id}] {chunk.text}")
        citation_dicts.append(citation.to_dict())

    return "\n\n".join(context_parts), citation_dicts


async def _tool_list_folder(
    session: AsyncSession,
    folder: Folder | None,
) -> tuple[str, list[dict[str, Any]]]:
    if folder is None:
        return "Error: No folder available.", []
    result = await session.execute(
        select(File).where(File.folder_id == folder.id)
    )
    files = result.scalars().all()

    if not files:
        return "No files found in this folder.", []

    lines = [
        f"- {f.name} (ID: {f.id}, type: {f.mime_type})"
        for f in sorted(files, key=lambda x: x.name)
    ]
    return "\n".join(lines), []


async def _tool_get_file_outline(
    session: AsyncSession,
    folder: Folder | None,
    file_name: str,
) -> tuple[str, list[dict[str, Any]]]:
    if folder is None:
        return "Error: No folder available.", []
    result = await session.execute(
        select(File).where(
            File.folder_id == folder.id,
            File.name == file_name,
        )
    )
    file = result.scalar_one_or_none()

    if not file:
        return f"File '{file_name}' not found.", []

    result = await session.execute(
        select(Chunk)
        .where(Chunk.file_id == file.id)
        .order_by(Chunk.ordinal)
    )
    chunks = result.scalars().all()

    lines = [f"File: {file.name}"]
    for c in chunks:
        chunk = cast(Chunk, c)
        lines.append(
            f"  {chunk.ordinal}. [{chunk.primary_unit_type}: {chunk.primary_unit_value}] "
            f"(chunk {chunk.id})"
        )
    return "\n".join(lines), []


async def _tool_read_section(
    session: AsyncSession,
    folder: Folder | None,
    file_name: str,
    primary_unit_type: str,
    primary_unit_value: str,
) -> tuple[str, list[dict[str, Any]]]:
    if folder is None:
        return "Error: No folder available.", []
    result = await session.execute(
        select(File).where(
            File.folder_id == folder.id,
            File.name == file_name,
        )
    )
    file = result.scalar_one_or_none()

    if not file:
        return f"File '{file_name}' not found.", []

    result = await session.execute(
        select(Chunk).where(
            Chunk.file_id == file.id,
            Chunk.primary_unit_type == primary_unit_type,
            Chunk.primary_unit_value == primary_unit_value,
        )
    )
    chunk = result.scalar_one_or_none()

    if not chunk:
        return (
            f"Section not found: {file_name} / "
            f"{primary_unit_type}:{primary_unit_value}",
            [],
        )

    found = cast(Chunk, chunk)
    return found.text, []


async def _tool_compare(
    session: AsyncSession,
    folder: Folder | None,
    file_name_a: str,
    file_name_b: str,
) -> tuple[str, list[dict[str, Any]]]:
    if folder is None:
        return "Error: No folder available.", []
    citations: list[dict[str, Any]] = []
    parts: list[str] = []

    for file_name in [file_name_a, file_name_b]:
        result = await session.execute(
            select(File).where(
                File.folder_id == folder.id,
                File.name == file_name,
            )
        )
        file = result.scalar_one_or_none()

        if not file:
            parts.append(f"=== {file_name} ===\nFile not found.")
            continue

        result = await session.execute(
            select(Chunk)
            .where(Chunk.file_id == file.id)
            .order_by(Chunk.ordinal)
        )
        chunks = result.scalars().all()

        file_parts = [f"=== {file.name} ==="]
        for c in chunks:
            chunk = cast(Chunk, c)
            citation = CitationBuilder.build(chunk, file.name)
            citations.append(citation.to_dict())
            file_parts.append(
                f"[citation:{chunk.id}] [{chunk.primary_unit_type}: "
                f"{chunk.primary_unit_value}]\n{chunk.text}"
            )
        parts.append("\n\n".join(file_parts))

    return "\n\n---\n\n".join(parts), citations


ToolHandler = Callable[..., Awaitable[tuple[str, list[dict[str, Any]]]]]

_TOOL_HANDLERS: dict[str, ToolHandler] = {
    "search": _tool_search,
    "list_folder": _tool_list_folder,
    "get_file_outline": _tool_get_file_outline,
    "read_section": _tool_read_section,
    "compare": _tool_compare,
}
