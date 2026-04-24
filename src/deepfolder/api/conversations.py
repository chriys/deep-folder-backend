import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from deepfolder.auth.dependencies import require_user
from deepfolder.config import settings
from deepfolder.db import get_session
from deepfolder.hybrid_search import HybridSearch
from deepfolder.llm_client import LLMClient
from deepfolder.models.conversation import Conversation, Message
from deepfolder.models.folder import Folder
from deepfolder.models.user import User
from deepfolder.query_router import QueryRouter
from deepfolder.services.agent_orchestrator import AgentOrchestrator
from deepfolder.usage_tracker import SpendCapExceeded, UsageTracker

router = APIRouter(prefix="/conversations")


class ConversationCreate(BaseModel):
    folder_id: int
    title: str | None = None


class MessageCreate(BaseModel):
    role: str
    content: str
    citations: dict | None = None


class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    citations: dict | None
    router_label: str | None
    created_at: str

    class Config:
        from_attributes = True


class ConversationResponse(BaseModel):
    id: int
    user_id: int
    folder_id: int
    title: str | None
    created_at: str
    updated_at: str
    messages: list[MessageResponse] = []

    class Config:
        from_attributes = True


class SendMessageRequest(BaseModel):
    content: str


def _make_llm() -> LLMClient:
    return LLMClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )


@router.post("", status_code=201, response_model=ConversationResponse)
async def create_conversation(
    payload: ConversationCreate,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_session),
) -> ConversationResponse:
    folder_result = await db.execute(
        select(Folder).where(Folder.id == payload.folder_id, Folder.user_id == user.id)
    )
    folder = folder_result.scalar_one_or_none()

    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    conversation = Conversation(
        user_id=user.id,
        folder_id=payload.folder_id,
        title=payload.title,
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)

    return ConversationResponse(
        id=conversation.id,
        user_id=conversation.user_id,
        folder_id=conversation.folder_id,
        title=conversation.title,
        created_at=conversation.created_at.isoformat(),
        updated_at=conversation.updated_at.isoformat(),
        messages=[],
    )


@router.get("")
async def list_conversations(
    folder_id: int | None = None,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_session),
) -> list[ConversationResponse]:
    query = select(Conversation).where(Conversation.user_id == user.id)

    if folder_id is not None:
        query = query.where(Conversation.folder_id == folder_id)

    result = await db.execute(query)
    conversations = result.scalars().all()

    return [
        ConversationResponse(
            id=conv.id,
            user_id=conv.user_id,
            folder_id=conv.folder_id,
            title=conv.title,
            created_at=conv.created_at.isoformat(),
            updated_at=conv.updated_at.isoformat(),
            messages=[
                MessageResponse(
                    id=msg.id,
                    conversation_id=msg.conversation_id,
                    role=msg.role,
                    content=msg.content,
                    citations=msg.citations,
                    router_label=msg.router_label,
                    created_at=msg.created_at.isoformat(),
                )
                for msg in sorted(conv.messages, key=lambda m: m.created_at)
            ],
        )
        for conv in conversations
    ]


@router.get("/{id}")
async def get_conversation(
    id: int,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_session),
) -> ConversationResponse:
    result = await db.execute(
        select(Conversation).where(Conversation.id == id, Conversation.user_id == user.id)
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return ConversationResponse(
        id=conversation.id,
        user_id=conversation.user_id,
        folder_id=conversation.folder_id,
        title=conversation.title,
        created_at=conversation.created_at.isoformat(),
        updated_at=conversation.updated_at.isoformat(),
        messages=[
            MessageResponse(
                id=msg.id,
                conversation_id=msg.conversation_id,
                role=msg.role,
                content=msg.content,
                citations=msg.citations,
                router_label=msg.router_label,
                created_at=msg.created_at.isoformat(),
            )
            for msg in sorted(conversation.messages, key=lambda m: m.created_at)
        ],
    )


@router.delete("/{id}", status_code=204)
async def delete_conversation(
    id: int,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_session),
) -> None:
    result = await db.execute(
        select(Conversation).where(Conversation.id == id, Conversation.user_id == user.id)
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await db.delete(conversation)
    await db.commit()


@router.post("/{id}/messages")
async def send_message(
    id: int,
    payload: SendMessageRequest,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_session),
):
    result = await db.execute(
        select(Conversation).where(Conversation.id == id, Conversation.user_id == user.id)
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    tracker = UsageTracker(db, user.id)
    try:
        await tracker.check_spend_cap()
    except SpendCapExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))

    user_msg = Message(
        conversation_id=id,
        role="user",
        content=payload.content,
    )
    db.add(user_msg)

    # Classify query
    llm = _make_llm()
    router = QueryRouter(llm)
    label = await router.classify(payload.content)
    user_msg.router_label = label

    if label == "simple":
        return await _handle_simple(
            db, id, conversation.folder_id, payload.content, llm, tracker
        )

    if label == "complex":
        folder_result = await db.execute(
            select(Folder).where(Folder.id == conversation.folder_id)
        )
        folder = folder_result.scalar_one_or_none()

        orchestrator = AgentOrchestrator(llm=llm, usage_tracker=tracker)
        return StreamingResponse(
            orchestrator.run(
                session=db,
                conversation=conversation,
                message=user_msg,
                folder=folder,
            ),
            media_type="text/event-stream",
        )

    return _handle_not_supported("task")


async def _handle_simple(
    db: AsyncSession,
    conversation_id: int,
    folder_id: int,
    query: str,
    llm: LLMClient,
    tracker: UsageTracker,
) -> StreamingResponse:
    """Simple path: retrieve top-K chunks, answer with nano LLM, stream via SSE."""
    search = HybridSearch()
    results = await search.retrieve(db, folder_id, query, k=10)

    context_parts = []
    citations = []
    for chunk, score, citation in results:
        context_parts.append(f"[citation:{chunk.id}] {chunk.text}")
        citations.append(citation.to_dict())

    context_text = "\n\n".join(context_parts)

    system_prompt = (
        "You are a helpful assistant that answers questions based on the provided document context.\n"
        "Each piece of context is tagged with a [citation:X] marker where X is the chunk ID.\n"
        "When you use information from a context piece, cite it by including the marker [citation:X].\n"
        "Only use the provided context to answer. If the context does not contain enough information, say so.\n"
        "Never fabricate citations or use citation markers not present in the context."
    )
    user_prompt = f"Context:\n{context_text}\n\nQuestion: {query}"

    async def event_stream():
        full_content = ""
        try:
            for c in citations:
                yield f"event: citation\ndata: {json.dumps({'citation': c})}\n\n"

            async for delta in llm.generate_stream(system_prompt, user_prompt):
                full_content += delta
                yield f"event: text_delta\ndata: {json.dumps({'delta': delta})}\n\n"

            assistant_msg = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=full_content,
                citations=citations,
            )
            db.add(assistant_msg)
            await db.commit()
            await db.refresh(assistant_msg)

            input_tokens = len(system_prompt + user_prompt) // 4
            output_tokens = len(full_content) // 4
            await tracker.record("llm", settings.llm_model, input_tokens, output_tokens)

            yield f"event: done\ndata: {json.dumps({'message_id': assistant_msg.id})}\n\n"
        except Exception:
            yield (
                f"event: error\ndata: {json.dumps({'code': 'internal_error', 'message': 'Failed to generate response'})}\n\n"
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _handle_not_supported(mode: str) -> StreamingResponse:
    """Return a 501 SSE error stream for complex/task modes."""

    async def event_stream():
        yield (
            f"event: error\ndata: {json.dumps({'code': 'not_implemented', 'message': f'{mode} mode not yet supported'})}\n\n"
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream", status_code=501)
