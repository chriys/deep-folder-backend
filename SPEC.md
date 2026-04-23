# Deep Folder Backend — v1 Spec

Locked decisions from the design grilling session. Each section records *what* and *why*.

---

## 1. Deployment model
- **Single-user MVP.** One user: you. No multi-tenancy, no OAuth consent screen review, no billing.
- Widen later via `ALLOWED_EMAILS` allowlist if teammates need access.

## 2. Runtime & language
- **Python 3.12.**

## 3. Web framework
- **FastAPI.** Async, SSE-friendly, Pydantic models as validation + tool schemas.

## 4. Storage
- **Postgres + pgvector + Postgres FTS (`tsvector` / `ts_rank_cd`).**
- Hybrid search fuses vector + FTS via Reciprocal Rank Fusion.
- One database for metadata, vectors, keyword index.

## 5. Google auth flow
- **Web App OAuth flow** through FastAPI.
- Routes: `GET /auth/google/start`, `GET /auth/google/callback`.
- Scope: `https://www.googleapis.com/auth/drive.readonly` only.
- Refresh token encrypted with Fernet (app-layer) before Postgres insert.

## 6. Folder ingestion scope
- **Recursive with limits.** Max depth 5, 500-file ceiling with user confirmation beyond.
- Per-subfolder embeddings *and* rolled-up folder embedding.

## 7. Supported file types (v1)

| Type | Extractor | Citation unit |
|---|---|---|
| Google Docs | `files.export` → text + html for structure | heading path + paragraph index |
| PDF | PyMuPDF (`fitz`) | page number + block index |
| Google Slides | Slides API export per slide | slide number |
| Google Sheets | Sheets API, per-sheet chunking | sheet name + row range |
| docx / pptx / xlsx | `python-docx` / `python-pptx` / `openpyxl` | paragraph / slide / sheet+row |
| txt / md | raw | line range or markdown heading path |

- Skipped: images (no OCR), audio/video, arbitrary binaries.
- Skipped files logged to `skipped_files` table.

## 8. Chunking
- **Structure-aware primary splits, ≤512-token secondary splits with 64-token overlap.**
- Primary boundary: PDF page, slide, sheet, Docs heading section, markdown heading section. No chunk crosses a primary boundary.
- Token counter: `tiktoken` cl100k_base (proxy, not exact).
- Per-chunk stored fields: `file_id`, `primary_unit` (typed), `sub_index`, `char_start`, `char_end`, `text`, `content_hash` (SHA-256).

## 9. Embeddings
- **Voyage `voyage-4`** for chunk embeddings (pin to current flagship at build time if name differs).
- Folder-level embeddings = both **mean-pooled chunk vector** *and* **summary-embedded vector**. Searched in parallel at query time.

## 10. Hybrid search
- Vector top-25 + BM25 top-25 → **Reciprocal Rank Fusion** (k=60) → **Voyage reranker** on top-50 → top 10–15 returned to agent.

## 11. Drive sync
- **Changes API + polling**, tick every 2–5 min via APScheduler.
- Per-user `start_page_token` stored in DB; changes filtered client-side to ingested folders.
- Manual `POST /folders/{id}/sync` endpoint for on-demand.
- No webhooks in v1.
- Re-embedding gated by per-chunk `content_hash`: unchanged chunks skip re-embedding.

## 12. Agent architecture
- **Agentic tool-use loop.** Hard cap: 15 tool calls per message.
- Orchestrator: **GPT-5.4 full.**
- **Query router** (nano classifier) runs first per message, returns one of:
  - `simple` → nano with retrieved context, no tool loop.
  - `complex` → full GPT-5.4 with tool loop.
  - `task` → full GPT-5.4 with tool loop, task-mode system prompt.
- Core tools:
  - `search(query, scope, top_k)`
  - `list_folder(folder_id)`
  - `get_file_outline(file_id)`
  - `read_section(file_id, unit_id, context_chunks=1)`
  - `compare(file_ids, question)`
  - `list_file_summaries(folder_id)`
  - `find_contradictions(folder_id, topic?)` (server-side candidate finder)
  - `synthesize_themes(folder_id)` (server-side clustering)
  - `run_task(task_type, params)`
- Prompt caching on system prompt + tool definitions.

## 13. Task mode
- **Separate `POST /tasks/run` endpoint** with fixed catalog and per-task Pydantic output schemas.
- v1 catalog: `extract_action_items`, `summarize`, `compare`, `extract_entities`.
- Agent can also invoke tasks via `run_task` tool.
- `GET /tasks/catalog` lists available task types + param schemas.

## 14. Conversation scope
- **One conversation = one folder.** `conversation.folder_id` required.
- Multi-folder conversations deferred; add `conversation_folders` join later if needed.

## 15. Citations
```jsonc
{
  "chunk_id": "uuid",
  "file_id": "drive_file_id",
  "file_name": "Q3 Report.pdf",
  "primary_unit": {
    "type": "pdf_page | slide | heading | sheet_range",
    "value": "..."
  },
  "quote": "exact text span",
  "deep_link": "https://docs.google.com/..."
}
```
- Anchor IDs (Docs heading IDs, Slides objectIds, Sheets gids) resolved **at ingest time** and stored per chunk.
- Office files in Drive: file-level link only (documented limitation).
- Agent never fabricates citations; tools return citation-ready metadata that agent passes through verbatim.

## 16. Background jobs
- **Postgres `jobs` table with `SELECT ... FOR UPDATE SKIP LOCKED`.**
- Schema: `(id, type, payload_jsonb, status, attempts, run_after, locked_by, locked_at, created_at, finished_at, error)`.
- Separate worker process polls the queue.
- **APScheduler** in its own process handles cron-style sync ticks.
- No Redis, no Celery.
- (Future option: swap APScheduler for Fly scheduled machines.)

## 17. Streaming
- **SSE (`text/event-stream`)** for both `POST /conversations/{id}/messages` and `POST /tasks/run`.
- Event types: `text_delta`, `tool_call_start`, `tool_call_result`, `citation`, `progress` (tasks), `done`, `error`.

## 18. Secrets & config
- `.env` loaded via `pydantic-settings`.
- Google refresh token encrypted with Fernet using `SECRET_KEY` before Postgres insert.
- `.env` gitignored; `.env.example` checked in.

## 19. Guardrails & cost controls
- Per-folder ingestion cap: 500 files (confirmation to exceed).
- Per-message tool-call cap: 15.
- **`usage` table** logs every LLM + embedding call: `(date, model, input_tokens, output_tokens, cost_usd)`.
- **Daily spend cap** from env (default $10). Hard-stop on exceed.
- Exponential backoff on all external APIs (`tenacity`), honor `Retry-After`.
- Chunk content-hash dedup: identical text reuses existing embedding.
- Voyage embedding batch size: 128.

## 20. Testing & eval
- **Unit tests** — extractors, chunkers, citation builders, deep-link builders, RRF math, hybrid search SQL.
- **Integration tests** — end-to-end ingest against a dedicated test Google account fixture folder (~15 files with known content).
- **Retrieval eval set** — 30+ hand-written `(question, expected_file_ids, expected_primary_units)` tuples. Tracked: recall@10 (≥0.8 to ship), MRR.
- **`traces` table** logs every agent tool call for replay / diffing.

## 21. Synthesis at scale
- **Map-reduce with pre-computed per-file artifacts.**
- At ingest, per file:
  - 300–500 token structured summary (nano).
  - `claims` list: discrete factual assertions with citations (nano).
- Query-time tools: `list_file_summaries`, `find_contradictions` (server-side claim-pair nearest-neighbor search), `synthesize_themes` (server-side clustering).
- Agent judges + narrates; does not pattern-match text directly.

## 22. API surface (v1)

**Auth**
- `GET  /auth/google/start`
- `GET  /auth/google/callback`
- `GET  /auth/status`
- `POST /auth/disconnect`

**Folders**
- `POST /folders` — body `{drive_url}`
- `GET  /folders`
- `GET  /folders/{id}`
- `POST /folders/{id}/sync`
- `DELETE /folders/{id}`

**Conversations**
- `POST /conversations` — body `{folder_id}`
- `GET  /conversations?folder_id=…`
- `GET  /conversations/{id}`
- `POST /conversations/{id}/messages` — SSE
- `DELETE /conversations/{id}`

**Tasks**
- `POST /tasks/run` — SSE
- `GET  /tasks/{id}`
- `GET  /tasks/catalog`

**Ops**
- `GET  /health`
- `GET  /usage?from=…&to=…`

No URL versioning yet; add `/v1` only when v2 is imminent.

## 23. Project layout & stack
```
deep-folder-backend/
  pyproject.toml              # uv
  .env.example
  alembic.ini
  alembic/
  src/deepfolder/
    __init__.py
    config.py                 # pydantic-settings
    db.py                     # async SQLAlchemy
    models/                   # ORM: users, folders, files, chunks, conversations,
                              #   messages, jobs, traces, usage, file_summaries,
                              #   claims, skipped_files
    schemas/                  # pydantic request/response + Citation + task outputs
    api/                      # routers: auth, folders, conversations, tasks, health
    auth/                     # Google OAuth client, token encryption, session
    drive/                    # Drive client, Changes API, export, deep-link builder,
                              #   URL parser
    ingest/                   # orchestrator, extractors/, chunker, anchor_resolver
    embedding/                # voyage client, folder-level embedding builder
    search/                   # vector, bm25, rrf, reranker
    agent/                    # orchestrator loop, tools/, router, prompts
    tasks/                    # task catalog, per-task handlers
    summarize/                # per-file summary + claims (nano)
    jobs/                     # job runner, scheduler, worker entrypoint
    sse.py
    logging.py
    errors.py
    main.py                   # FastAPI app factory
  tests/
    unit/ integration/ eval/
    fixtures/
  scripts/
    run_worker.py run_scheduler.py ingest_fixture.py
```

- **Deps/package**: `uv`.
- **ORM + migrations**: SQLAlchemy 2.x async + Alembic (autogenerated migrations hand-reviewed).
- **HTTP**: `httpx` + `tenacity`.
- **Google**: `google-api-python-client` + `google-auth-oauthlib`.
- **Lint/format**: `ruff` + `ruff format` only.
- **Types**: `mypy --strict src/deepfolder` (CI gate).
- **Tests**: `pytest`, `pytest-asyncio`, `pytest-postgresql`.

## 24. Deploy target
- **Fly.io from day one.**
- One image, three processes via `[processes]` in `fly.toml`: `api`, `worker`, `scheduler`.
- Fly Postgres with pgvector extension (`CREATE EXTENSION vector` post-provision).
- Deploy via `fly deploy` (from CI).
- Alembic runs via `release_command` before new image serves traffic.

## 25. Frontend ↔ backend auth
- Google OAuth doubles as app auth.
- `ALLOWED_EMAILS` env allowlist; callback rejects anyone else with 403.
- **HttpOnly signed session cookie** (starlette `SessionMiddleware` or `itsdangerous`), flags: `HttpOnly`, `Secure`, `SameSite=Lax`, 30-day rolling expiry.
- `require_user` FastAPI dependency on every non-auth route.
- Cookie scoping: same parent domain or frontend mounted by FastAPI.

## 26. Observability
- **Logs**: `structlog` → JSON to stdout, captured by Fly.
- **Errors**: Sentry with FastAPI integration, release tagging.
- **LLM traces**: `traces` table (mandatory) + Langfuse (optional via env flag).
- **Metrics**: Fly built-in + `usage` table. No Prometheus in v1.

## 27. CI/CD — GitHub Actions
**`ci.yml` (PR + push to main):**
- `uv sync`
- `ruff check` + `ruff format --check`
- `mypy --strict`
- `pytest tests/unit` (always)
- `pytest tests/integration` (main-only; Postgres service container + test Google creds from secrets)
- `pytest tests/eval` with recall@10 threshold gate

**`deploy.yml` (push to main after ci green):**
- `flyctl deploy --remote-only` using `FLY_API_TOKEN`.
- Alembic migration as Fly release command.

**Secrets**: `FLY_API_TOKEN`, `SENTRY_DSN`, test Google refresh token.

**Branch protection**: main requires CI green.

## 28. Shared Drives & URL parsing
- **My Drive only in v1.** Shared Drive URLs rejected with clear error ("Shared Drives not yet supported").
- URL parser accepts:
  - `https://drive.google.com/drive/folders/{id}`
  - `?usp=sharing` variants
  - `/drive/u/0/folders/{id}`
  - raw folder IDs
- Regex: `folders/([a-zA-Z0-9_-]+)`, fallback to raw-ID pattern match.

## 29. MVP sequencing

**v0.1 — walking skeleton (1–2 wk):**
- OAuth + allowlist + session cookie.
- Paste folder URL → ingest **PDFs + Google Docs only**.
- Structure-aware chunking, Voyage embeddings, pgvector only (no BM25).
- Single LLM call with top-K context (no agent loop, no router).
- Conversations + messages persisted, SSE streaming.
- Page/heading-level citations + deep links.
- Fly deploy. Manual re-ingest.

**v0.2 — retrieval quality + scope:**
- BM25 + RRF + Voyage reranker.
- Slides, Sheets, Office extractors.
- Agentic tool loop + nano router.
- Tool-call cap, `traces` table.

**v0.3 — scale + sync:**
- Drive Changes API polling + sync jobs.
- Content-hash dedup.
- Per-file summaries + claims at ingest.
- Folder-level embeddings (pooled + summary).

**v0.4 — advanced features:**
- Task mode `/tasks/run` + catalog.
- `find_contradictions` + `synthesize_themes` server-side tools.
- Optional Langfuse instrumentation.
- Retrieval eval set gated in CI.

**v0.5 — polish:**
- Skipped-files surface, error UX, usage dashboard, daily spend cap enforcement.
