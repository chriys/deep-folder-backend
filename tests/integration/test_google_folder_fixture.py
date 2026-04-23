"""End-to-end integration test against a fixture Google Drive folder.

Gated behind INTEGRATION_TEST=1. Requires:
  - INTEGRATION_TEST=1
  - TEST_FOLDER_ID       -- Google Drive folder ID containing the fixture files
  - TEST_REFRESH_TOKEN   -- pre-authorized Google refresh token (plaintext;
                            encrypted by the test via TokenVault)
  - VOYAGE_API_KEY       -- for chunk embeddings (from settings)
  - LLM_API_KEY          -- (optional) for the LLM round-trip assertion

The fixture is documented in tests/fixture/google_folder.py.
"""

import json
import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from deepfolder.auth.dependencies import require_user
from deepfolder.auth.token_vault import TokenVault
from deepfolder.config import settings
from deepfolder.db import get_session
from deepfolder.hybrid_search import HybridSearch
from deepfolder.job_queue import JobQueue, JobHandlers
from deepfolder.main import create_app
from deepfolder.models.chunk import Chunk
from deepfolder.models.conversation import Conversation, Message
from deepfolder.models.file import File
from deepfolder.models.folder import Folder
from deepfolder.models.job import Job
from deepfolder.models.user import User
from deepfolder.citation_builder import CitationBuilder

from tests.fixture.google_folder import (
    FILES,
    MIN_FILE_COUNT,
    MAX_FILE_COUNT,
    MIN_CHUNK_COUNT,
    MAX_CHUNK_COUNT,
    KNOWN_QUESTIONS,
)


pytestmark = pytest.mark.skipif(
    not os.environ.get("INTEGRATION_TEST")
    or not os.environ.get("TEST_FOLDER_ID")
    or not os.environ.get("TEST_REFRESH_TOKEN"),
    reason="Set INTEGRATION_TEST=1, TEST_FOLDER_ID, and TEST_REFRESH_TOKEN",
)


def _parse_sse(text: str) -> list[dict]:
    """Parse SSE event stream into list of {event, data} dicts."""
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_type = None
        data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if event_type and data is not None:
            events.append({"event": event_type, "data": data})
    return events


@pytest.mark.asyncio
async def test_google_folder_fixture_end_to_end(async_session: AsyncSession):
    """Full end-to-end test: ingest -> embed -> retrieve -> LLM answer -> citation shape."""
    folder_id = os.environ["TEST_FOLDER_ID"]
    refresh_token = os.environ["TEST_REFRESH_TOKEN"]

    # ------------------------------------------------------------------
    # 1. Create user with encrypted refresh token
    # ------------------------------------------------------------------
    vault = TokenVault(settings.secret_key)
    encrypted_token = vault.encrypt(refresh_token)

    user = User(email="integration-test@deepfolder.dev", encrypted_refresh_token=encrypted_token)
    async_session.add(user)
    await async_session.flush()
    user_id = user.id

    # ------------------------------------------------------------------
    # 2. Create folder + ingest job
    # ------------------------------------------------------------------
    folder = Folder(
        user_id=user_id,
        drive_folder_id=folder_id,
        name="Integration Test Fixture",
        state="pending",
    )
    async_session.add(folder)
    await async_session.flush()
    folder_pk = folder.id

    job = Job(
        job_type="ingest_folder",
        status="pending",
        payload=json.dumps({"folder_id": folder_pk}),
        user_id=user_id,
    )
    async_session.add(job)
    await async_session.commit()

    # ------------------------------------------------------------------
    # 3. Run the ingest handler
    # ------------------------------------------------------------------
    dequeued = await JobQueue.dequeue_job(async_session)
    assert dequeued is not None, "No pending ingest job found"
    await JobQueue.mark_in_progress(async_session, dequeued.id)
    await JobHandlers.execute(async_session, dequeued)
    await JobQueue.mark_complete(async_session, dequeued.id)

    # ------------------------------------------------------------------
    # 4. Verify folder state -> ready, file count within range
    # ------------------------------------------------------------------
    result = await async_session.execute(select(Folder).where(Folder.id == folder_pk))
    folder = result.scalar_one()
    assert folder.state == "ready", f"Folder state is {folder.state!r}, expected 'ready'"
    assert MIN_FILE_COUNT <= folder.file_count <= MAX_FILE_COUNT, (
        f"File count {folder.file_count} not in "
        f"[{MIN_FILE_COUNT}, {MAX_FILE_COUNT}]"
    )

    # ------------------------------------------------------------------
    # 5. Verify expected files exist with correct mime types
    # ------------------------------------------------------------------
    for file_def in FILES:
        result = await async_session.execute(
            select(File).where(File.folder_id == folder_pk, File.name == file_def["name"])
        )
        file_obj = result.scalar_one_or_none()
        assert file_obj is not None, f"Expected file not found: {file_def['name']}"
        assert file_obj.mime_type == file_def["mime_type"], (
            f"File {file_def['name']}: expected mime {file_def['mime_type']}, "
            f"got {file_obj.mime_type}"
        )

    # ------------------------------------------------------------------
    # 6. Verify chunk count within documented bounds
    # ------------------------------------------------------------------
    result = await async_session.execute(
        select(func.count()).select_from(Chunk).join(File).where(File.folder_id == folder_pk)
    )
    chunk_count = result.scalar()
    assert MIN_CHUNK_COUNT <= chunk_count <= MAX_CHUNK_COUNT, (
        f"Chunk count {chunk_count} not in [{MIN_CHUNK_COUNT}, {MAX_CHUNK_COUNT}]"
    )

    # ------------------------------------------------------------------
    # 7. Citation shape assertion
    #    Every chunk must produce a valid Citation; deep_link must point
    #    to a real Drive or Docs URL.
    # ------------------------------------------------------------------
    result = await async_session.execute(
        select(Chunk).join(File).where(File.folder_id == folder_pk)
    )
    chunks = result.scalars().all()

    for chunk in chunks:
        # deep_link must be a valid Google Drive or Docs URL
        is_valid = chunk.deep_link.startswith("https://drive.google.com/") or chunk.deep_link.startswith(
            "https://docs.google.com/"
        )
        assert is_valid, f"Invalid deep_link for chunk {chunk.id}: {chunk.deep_link!r}"

        # Citation builder must produce a schema-conformant Citation
        result = await async_session.execute(select(File).where(File.id == chunk.file_id))
        file_obj = result.scalar_one()
        citation = CitationBuilder.build(chunk, file_obj.name)
        assert citation.chunk_id == chunk.id
        assert citation.file_id == chunk.file_id
        assert citation.file_name == file_obj.name
        assert citation.deep_link == chunk.deep_link
        serialized = citation.to_dict()
        assert "primary_unit" in serialized
        assert serialized["primary_unit"]["type"] == chunk.primary_unit_type
        assert serialized["primary_unit"]["value"] == chunk.primary_unit_value

    # ------------------------------------------------------------------
    # 8. Known-answer retrieval
    #    For each (question, expected_file), verify the expected file
    #    appears in top-10 retrieval results.
    # ------------------------------------------------------------------
    search = HybridSearch()
    for kq in KNOWN_QUESTIONS:
        results = await search.retrieve(async_session, folder_pk, kq["question"], k=10)
        file_names_in_results = {citation.file_name for _, _, citation in results}
        assert kq["expected_file"] in file_names_in_results, (
            f"Known-answer retrieval failed for question: {kq['question']!r}. "
            f"Expected file {kq['expected_file']!r} not in {file_names_in_results}"
        )

    # ------------------------------------------------------------------
    # 9. Known-answer LLM round trip (requires LLM_API_KEY)
    #    Create a conversation, send a message, verify the SSE stream
    #    contains citation events with valid shape and a non-empty answer.
    # ------------------------------------------------------------------
    if not os.environ.get("LLM_API_KEY"):
        pytest.skip("LLM_API_KEY not set, skipping LLM round-trip test")

    conversation = Conversation(user_id=user_id, folder_id=folder_pk, title="Integration Test")
    async_session.add(conversation)
    await async_session.commit()
    await async_session.refresh(conversation)

    app = create_app()

    async def _override_session():
        yield async_session

    async def _override_user():
        return user

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[require_user] = _override_user

    question = KNOWN_QUESTIONS[0]["question"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/conversations/{conversation.id}/messages",
            json={"content": question},
        )

    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("text/event-stream")

    events = _parse_sse(response.text)
    assert len(events) >= 3, f"Expected >= 3 SSE events, got {len(events)}"

    # Citation events: at least one with valid shape
    citation_events = [e for e in events if e["event"] == "citation"]
    assert len(citation_events) > 0, "No citation events in SSE response"
    for ce in citation_events:
        c = ce["data"]["citation"]
        assert "chunk_id" in c
        assert "file_id" in c
        assert "file_name" in c
        assert "primary_unit" in c
        assert "quote" in c
        assert "deep_link" in c
        assert c["deep_link"].startswith("https://drive.google.com/") or c["deep_link"].startswith(
            "https://docs.google.com/"
        ), f"Invalid citation deep_link: {c['deep_link']!r}"

    # Text delta events: at least one, non-empty combined text
    text_events = [e for e in events if e["event"] == "text_delta"]
    assert len(text_events) > 0, "No text_delta events in SSE response"
    full_text = "".join(e["data"]["delta"] for e in text_events)
    assert len(full_text) > 0, "Empty assistant response"

    # Done event: exactly one with message_id
    done_events = [e for e in events if e["event"] == "done"]
    assert len(done_events) == 1, f"Expected 1 done event, got {len(done_events)}"
    assert "message_id" in done_events[0]["data"]

    # Verify assistant message was persisted
    msg_id = done_events[0]["data"]["message_id"]
    result = await async_session.execute(select(Message).where(Message.id == msg_id))
    persisted = result.scalar_one_or_none()
    assert persisted is not None, "Assistant message was not persisted"
    assert persisted.role == "assistant"
    assert persisted.citations is not None
    assert len(persisted.citations) > 0
