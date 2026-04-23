from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.auth.dependencies import require_user
from deepfolder.config import settings
from deepfolder.db import get_session
from deepfolder.hybrid_search import HybridSearch
from deepfolder.llm_client import LLMClient
from deepfolder.models.conversation import Conversation, Message
from deepfolder.models.folder import Folder
from deepfolder.models.user import User
from deepfolder.usage_tracker import UsageTracker, SpendCapExceeded

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


class SendMessageResponse(BaseModel):
    message_id: int
    content: str
    citations: list[dict]


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


@router.post("/{id}/messages", status_code=201)
async def send_message(
    id: int,
    payload: SendMessageRequest,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_session),
) -> SendMessageResponse:
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

    # Persist user message
    user_msg = Message(
        conversation_id=id,
        role="user",
        content=payload.content,
    )
    db.add(user_msg)

    # Retrieve top-K chunks from the bound folder
    search = HybridSearch()
    results = await search.retrieve(db, conversation.folder_id, payload.content, k=10)

    # Build context string and citations
    context_parts = []
    citations = []
    for chunk, score, citation in results:
        context_parts.append(f"[citation:{chunk.id}] {chunk.text}")
        citations.append(citation.to_dict())

    context_text = "\n\n".join(context_parts)

    # Call LLM with context
    llm = LLMClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )
    system_prompt = (
        "You are a helpful assistant that answers questions based on the provided document context.\n"
        "Each piece of context is tagged with a [citation:X] marker where X is the chunk ID.\n"
        "When you use information from a context piece, cite it by including the marker [citation:X].\n"
        "Only use the provided context to answer. If the context does not contain enough information, say so.\n"
        "Never fabricate citations or use citation markers not present in the context."
    )
    user_prompt = f"Context:\n{context_text}\n\nQuestion: {payload.content}"
    assistant_content, input_tokens, output_tokens = await llm.generate(system_prompt, user_prompt)

    await tracker.record("llm", settings.llm_model, input_tokens, output_tokens)

    # Persist assistant message with citations
    assistant_msg = Message(
        conversation_id=id,
        role="assistant",
        content=assistant_content,
        citations=citations,
    )
    db.add(assistant_msg)
    await db.commit()
    await db.refresh(assistant_msg)

    return SendMessageResponse(
        message_id=assistant_msg.id,
        content=assistant_content,
        citations=citations,
    )
