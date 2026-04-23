# PRD: Deep Folder Backend v1 — talk to a Drive folder

## Problem Statement

I routinely work out of Google Drive folders that hold dozens of long, heterogeneous documents — Q3/Q4 reports, meeting notes, proposals, spreadsheets, slide decks. Finding a specific claim, comparing what two documents say, spotting where they disagree, or synthesizing themes across a folder currently means opening every file and reading manually. Existing Drive search is filename/keyword-based and has no sense of structure, argument, or cross-document reasoning. Generic chat-with-your-docs tools either don't integrate with Drive properly, lose track of where a claim came from, re-ingest everything on every edit, or degrade badly past a handful of files.

## Solution

A backend service I can point at any Google Drive folder URL and then have real conversations with its contents. The service:

- Authenticates my Google account and ingests the whole folder recursively (PDFs, Docs, Slides, Sheets, Office, txt/md).
- Indexes every file into structure-aware Chunks and embeddings, and precomputes a File Summary plus a list of Claims per file for cheap synthesis at query time.
- Answers questions through an agent with a tool loop that can search, compare documents, list summaries, surface contradictions, and synthesize themes — with every answer carrying Citations that deep-link back to the exact page, slide, heading, or sheet range.
- Exposes a Task mode (`extract_action_items`, `summarize`, `compare`, `extract_entities`) with a structured schema per Task for workflow operations that aren't conversations.
- Keeps itself in sync with Drive via a polling loop against the Drive Changes API, re-embedding only the Chunks whose text actually changed.

The single canonical specification for locked decisions is [`SPEC.md`](./SPEC.md); the canonical vocabulary is [`UBIQUITOUS_LANGUAGE.md`](./UBIQUITOUS_LANGUAGE.md).

## User Stories

### Authentication & access

1. As the User, I want to click "Connect Google" and complete a consent flow, so that the backend can read my Drive on my behalf.
2. As the User, I want my Google refresh token stored encrypted at the app layer with Fernet, so that a database leak alone does not expose Drive access.
3. As the User, I want only emails in the `ALLOWED_EMAILS` allowlist to be able to authenticate, so that the MVP stays single-user even if the URL is shared.
4. As the User, I want a session cookie (HttpOnly, Secure, SameSite=Lax, 30-day rolling) issued after successful OAuth, so that I don't re-authenticate on every request.
5. As the User, I want `GET /auth/status` to tell me whether my Drive connection is healthy, so that I know before I paste a folder URL.
6. As the User, I want `POST /auth/disconnect` to revoke and delete my stored token, so that I can sever the integration cleanly.

### Folder ingestion

7. As the User, I want to paste any Drive folder URL shape (`drive/folders/{id}`, `?usp=sharing`, `/drive/u/0/folders/{id}`, or raw ID) and have it parsed, so that I don't have to hand-clean URLs.
8. As the User, I want Shared Drive URLs rejected with a clear "Shared Drives not yet supported" error, so that I'm not left wondering why an ingest produced nothing.
9. As the User, I want the folder crawled recursively up to depth 5 with a 500-file ceiling, so that I don't accidentally ingest my entire Drive.
10. As the User, I want a confirmation prompt before ingesting folders above the 500-file ceiling, so that large runs are deliberate.
11. As the User, I want PDFs, Google Docs, Google Slides, Google Sheets, docx, pptx, xlsx, txt, and md ingested, so that I cover everything I actually keep in work folders.
12. As the User, I want images, audio, video, and arbitrary binaries skipped and logged to a `skipped_files` table with a reason, so that I can see what was left out.
13. As the User, I want ingestion to run as a background Job with progress visible, so that the HTTP request doesn't block on a long crawl.
14. As the User, I want `GET /folders` and `GET /folders/{id}` to show me what's been ingested and its current state, so that I can audit the system's knowledge.
15. As the User, I want `DELETE /folders/{id}` to remove a Folder and all its derived artifacts, so that I can clean up experiments.

### Chunking & citations

16. As the User, I want every Chunk bounded by a natural Primary Unit (PDF page, slide, sheet range, heading section), so that citations line up with how I actually think about the document.
17. As the User, I want long Primary Units split into ≤512-token Chunks with 64-token overlap, so that retrieval stays precise on dense pages without losing context across the split.
18. As the User, I want every Chunk carrying a `content_hash`, so that the Sync pipeline can skip Re-embedding when nothing changed.
19. As the User, I want Anchor IDs (Docs heading IDs, Slides objectIds, Sheets gids) resolved at ingest time and stored per Chunk, so that citations deep-link to the right spot even if we cached the file content.
20. As the User, I want every agent answer to return Citations with `file_id`, `file_name`, `primary_unit`, `quote`, and `deep_link`, so that I can click straight into Drive and verify.
21. As the User, I want the Agent to never fabricate a citation — tools return citation-ready metadata that the Orchestrator passes through verbatim — so that I can trust every link.
22. As the User, I want Office files (docx/pptx/xlsx) stored in Drive to produce file-level Deep Links rather than fake internal anchors, so that citations remain honest about platform limitations.

### Retrieval

23. As the User, I want Hybrid Search (Vector + Keyword) fused by RRF (k=60) and reranked by Voyage, so that I get high-recall but well-ordered results regardless of whether my query is conceptual or lexical.
24. As the User, I want `voyage-4` used for Chunk Embeddings, so that I'm on the current Voyage flagship.
25. As the User, I want both a Pooled Folder Embedding and a Summary Folder Embedding per folder, so that "what is this folder about" high-level questions route differently from specific-content questions.
26. As the User, I want identical Chunk text to reuse an existing Chunk Embedding via `content_hash` dedup, so that I'm not paying to re-embed boilerplate.

### Agent & conversation

27. As the User, I want each Conversation bound to exactly one Folder, so that context is unambiguous.
28. As the User, I want a Query Router (nano classifier) to label each Message `simple | complex | task`, so that cheap questions don't pay for the full Tool Loop.
29. As the User, I want `simple` queries answered by nano with retrieved context and no Tool Loop, so that basic lookups stay fast and cheap.
30. As the User, I want `complex` queries dispatched to the GPT-5.4 Orchestrator with a Tool Loop hard-capped at 15 Tool Calls, so that the Agent can plan but not spiral.
31. As the User, I want Tools for `search`, `list_folder`, `get_file_outline`, `read_section`, `compare`, `list_file_summaries`, `find_contradictions`, `synthesize_themes`, and `run_task`, so that the Orchestrator has leverage without having to pattern-match raw text for everything.
32. As the User, I want `find_contradictions` implemented server-side as a nearest-neighbor search over Claim pairs across Files, so that contradiction detection is grounded in precomputed facts rather than the LLM eyeballing chunks.
33. As the User, I want `synthesize_themes` implemented as server-side clustering over File Summaries, so that "summarize all files into themes" works deterministically across hundreds of files.
34. As the User, I want the Orchestrator to stream responses via SSE with event types for `text_delta`, `tool_call_start`, `tool_call_result`, `citation`, `done`, and `error`, so that the UI can render progressively.
35. As the User, I want Conversations and Messages persisted, so that I can revisit past threads.

### Task mode

36. As the User, I want `GET /tasks/catalog` to enumerate available Task types with their parameter and output schemas, so that clients can build UI without hardcoding.
37. As the User, I want `POST /tasks/run` to execute `extract_action_items`, `summarize`, `compare`, or `extract_entities` over a Folder with a typed Pydantic output, so that I can pipe results into other systems.
38. As the User, I want Task Runs streamed over SSE with a `progress` event type, so that long extractions are legible.
39. As the User, I want the Orchestrator able to invoke the same Task handlers via a `run_task` Tool, so that tasks inside a Conversation and direct Task Runs share one implementation.

### Sync

40. As the User, I want a Sync Tick every 2–5 minutes per Folder via APScheduler hitting the Drive Changes API, so that my index tracks Drive without webhooks.
41. As the User, I want Drive Changes filtered client-side to ingested Folders, so that I'm not processing irrelevant changes elsewhere in my Drive.
42. As the User, I want `POST /folders/{id}/sync` to trigger an immediate Manual Sync, so that I don't have to wait for the next scheduled tick.
43. As the User, I want Re-embedding to fire only for Chunks whose `content_hash` changed, so that editing one paragraph in a 200-page PDF costs one or two embeddings, not hundreds.
44. As the User, I want File Summaries and Claims regenerated when a File's chunks change, so that synthesis artifacts stay consistent with the source.

### Background infrastructure

45. As the User, I want Jobs persisted in Postgres (`SELECT ... FOR UPDATE SKIP LOCKED`), so that I don't need Redis or Celery.
46. As the User, I want a dedicated Worker process and a dedicated Scheduler process alongside the API, so that long ingests don't block HTTP.
47. As the User, I want Jobs to record attempts and errors, so that I can diagnose failed ingests without re-reading logs.

### Observability & cost

48. As the User, I want every LLM and embedding call logged to a `usage` table with token counts and USD cost, so that I know what this thing costs day to day.
49. As the User, I want a configurable daily Spend Cap (default $10) that hard-stops further calls on exceed, so that a runaway agent doesn't drain my wallet overnight.
50. As the User, I want every Orchestrator call and Tool Call written to a `traces` table, so that I can replay and diff behavior when the Agent misbehaves.
51. As the User, I want structured JSON logs to stdout via `structlog` and errors forwarded to Sentry, so that Fly captures them without extra infrastructure.
52. As the User, I want `GET /usage?from=…&to=…` to return cost and token rollups, so that I can check spend without hitting the DB directly.

### Deploy & operations

53. As the User, I want Fly.io deployment from day one with one image and three processes (`api`, `worker`, `scheduler`) via `fly.toml`, so that the system runs as in production immediately.
54. As the User, I want Alembic migrations to run via Fly's `release_command` before new traffic is served, so that schema drift can't happen mid-deploy.
55. As the User, I want `GET /health` for liveness, so that Fly can probe it.
56. As the User, I want GitHub Actions to run `ruff`, `mypy --strict`, and unit tests on every PR, and deploy to Fly on merge to main, so that I don't ship unchecked code.
57. As the User, I want `main` branch-protected to require green CI, so that broken code can't reach production.

## Implementation Decisions

All locked decisions live in [`SPEC.md`](./SPEC.md). The short version:

**Stack & packaging**
- Python 3.12 + FastAPI (async) + Pydantic v2
- Package manager: `uv`; ORM: SQLAlchemy 2.x async + Alembic
- Lint/format: `ruff` + `ruff format`; Types: `mypy --strict` as CI gate
- HTTP: `httpx` + `tenacity`; Google: `google-api-python-client` + `google-auth-oauthlib`
- Deploy: Fly.io, one image, three processes (`api`, `worker`, `scheduler`); Fly Postgres with pgvector

**Storage**
- Single Postgres database holding metadata, vectors (pgvector), and keyword index (`tsvector` / `ts_rank_cd`)
- Core tables: `users`, `folders`, `files`, `chunks`, `conversations`, `messages`, `jobs`, `traces`, `usage`, `skipped_files`, `file_summaries`, `claims`

**Modules** (target deep modules with stable interfaces; detailed responsibilities in SPEC.md §23 layout):
1. `DriveClient` — Google OAuth, Drive metadata/export, Changes API, folder URL parsing, Deep-Link builder
2. `Extractor` protocol + per-type implementations (PDF, Docs, Slides, Sheets, docx/pptx/xlsx, txt/md)
3. `Chunker` — structure-aware Primary Unit splits + ≤512-token secondary splits + 64-token overlap + content hashing
4. `EmbeddingClient` — Voyage `voyage-4` chunk embeddings + folder-level builder (pooled + summary vectors)
5. `HybridSearch` — vector + keyword legs, RRF (k=60), Voyage reranker on top-50 → top 10–15
6. `CitationBuilder` — turn Chunk + stored anchors into the Citation payload
7. `QueryRouter` — nano classifier: `simple | complex | task`
8. `AgentOrchestrator` — GPT-5.4 full Tool Loop, 15-call cap, prompt caching on system prompt + tool defs
9. `TaskRunner` — Task Catalog, per-task handlers, Pydantic output schemas; shared with `run_task` Tool
10. `JobQueue` — Postgres `SELECT ... FOR UPDATE SKIP LOCKED`, attempts, errors, `run_after`
11. `IngestService` — orchestrates first-time ingest and Sync (formerly IngestOrchestrator + SyncService, collapsed per design review)
12. `InsightService` — per-File Summary + Claims at ingest, `find_contradictions`, `synthesize_themes` (formerly FileSummarizer + ContradictionFinder + ThemeSynthesizer, collapsed)
13. `AuthService` — Google OAuth Web flow, session cookie, `ALLOWED_EMAILS` enforcement
14. `TokenVault` — Fernet encryption of refresh tokens at rest
15. `UsageTracker` — usage-row writes, daily Spend Cap enforcement

**Interfaces (high-level contracts; see SPEC.md §22 for endpoint list)**
- Auth: `GET /auth/google/start`, `GET /auth/google/callback`, `GET /auth/status`, `POST /auth/disconnect`
- Folders: `POST /folders {drive_url}`, `GET /folders`, `GET /folders/{id}`, `POST /folders/{id}/sync`, `DELETE /folders/{id}`
- Conversations: `POST /conversations {folder_id}`, `GET /conversations?folder_id=…`, `GET /conversations/{id}`, `POST /conversations/{id}/messages` (SSE), `DELETE /conversations/{id}`
- Tasks: `POST /tasks/run` (SSE), `GET /tasks/{id}`, `GET /tasks/catalog`
- Ops: `GET /health`, `GET /usage?from=…&to=…`
- No URL versioning (no `/v1` prefix) until v2 is imminent.

**Citation schema**
- Fixed Pydantic shape: `{chunk_id, file_id, file_name, primary_unit: {type, value}, quote, deep_link}`
- Anchor resolution at ingest time, stored per Chunk
- Office files → file-level Deep Link only; documented limitation

**Model choices**
- Orchestrator: GPT-5.4 full
- Query Router + simple-query answerer + ingest-time File Summary + Claims: GPT-5.4 nano (two-tier model strategy, confirmed during grilling)
- Embeddings: Voyage `voyage-4` (pin to current flagship at build)
- Reranker: Voyage cross-encoder

**Synthesis strategy**
- Map-reduce at ingest: one File Summary + one Claim list per file (both nano)
- Query-time synthesis tools operate on precomputed artifacts (`list_file_summaries`, `find_contradictions`, `synthesize_themes`)
- Orchestrator judges and narrates; does not text-match raw chunks for synthesis

**Sync strategy**
- Drive Changes API + APScheduler polling every 2–5 min/Folder
- Per-user `start_page_token` stored; no webhooks in v1
- `content_hash` gates Re-embedding

**Security & config**
- `.env` loaded via `pydantic-settings`, gitignored; `.env.example` checked in
- Fernet `SECRET_KEY` encrypts refresh tokens
- Google OAuth doubles as app auth; `ALLOWED_EMAILS` enforcement in callback; session cookie (HttpOnly, Secure, SameSite=Lax, 30-day rolling)
- Scope: `drive.readonly` only

**Guardrails**
- 500-file folder cap with confirmation
- 15-tool-call cap per Message
- Daily Spend Cap (env, default $10) enforced in `UsageTracker`
- Tenacity exponential backoff on all external calls, honoring `Retry-After`
- Voyage embedding batch size: 128

## Testing Decisions

**What makes a good test**
- Test observable external behavior, not internal wiring
- Prefer real Postgres (via `pytest-postgresql`) over mocks so pgvector + FTS SQL is actually exercised
- Integration tests hit a dedicated test Google account fixture folder (~15 files with known content)
- Mocks only for outbound LLM/embedding/Drive HTTP where replay is unnecessary

**v0.1 test targets (walking skeleton)**
- Unit: `Chunker` (primary-unit boundaries, overlap math, token-count behavior, content-hash stability)
- Unit: `CitationBuilder` (schema correctness, deep-link shape per primary unit type, quote fidelity)
- Unit: `JobQueue` (`SKIP LOCKED` semantics under concurrent workers, attempt counters, `run_after` gating)
- Unit: `TokenVault` (Fernet round-trip; stored ciphertext ≠ plaintext; rotation path documented)
- Unit: `DriveClient.parse_folder_url` (all URL shapes, raw ID fallback, Shared Drive rejection)
- Integration: end-to-end ingest against the test Google fixture (3 fixture PDFs + 2 Google Docs); assertions on file count, chunk count, citation shape, and a known-answer retrieval round trip

**v0.2+ test additions (land with features)**
- Unit: RRF math, BM25 SQL ranking sanity, reranker call shape (v0.2)
- Unit: Query Router classification on a labeled fixture set (v0.2)
- Unit: `find_contradictions` nearest-neighbor logic, `synthesize_themes` clustering on a synthetic Claim set (v0.4)
- Retrieval eval set (v0.4): 30+ hand-written `(question, expected_file_ids, expected_primary_units)` tuples; recall@10 ≥ 0.8 gated in CI; MRR tracked
- Integration: full agent loop against fixture folder with deterministic seed and replay from `traces` table (v0.2+)

**Prior art**
- None in this greenfield repo. Patterns to borrow from wider Python ecosystem:
  - `pytest-postgresql` fixtures for async SQLAlchemy testing
  - Replay-style tests driven by `traces` rows for agent behavior

## Out of Scope

- **Multi-tenancy.** v1 is single-user. `ALLOWED_EMAILS` can expand the allowlist but the data model stays flat.
- **Shared Drives.** Rejected at the URL parser with a clear error in v1.
- **OCR.** Image files, scanned PDFs without text layers, audio, and video are skipped and logged, not processed.
- **Webhooks for Drive push notifications.** Polling via Changes API only in v1.
- **Multi-folder conversations.** One Conversation = one Folder. Cross-folder synthesis deferred.
- **URL-versioned API (`/v1`).** Added only when v2 is imminent.
- **Prometheus / custom metrics stack.** Fly built-in metrics + `usage` table suffice for v1.
- **Redis, Celery, RabbitMQ.** Postgres `SKIP LOCKED` + APScheduler only.
- **Real-time collaborative editing detection beyond the 2–5 min tick.** Manual Sync covers the impatient case.
- **Per-user billing, quotas, rate limits beyond the daily Spend Cap.**
- **Fine-tuned models, custom embeddings, local inference.** Flagship hosted models only.

## Further Notes

**Canonical references**
- Locked design decisions: [`SPEC.md`](./SPEC.md) (29 sections)
- Canonical vocabulary: [`UBIQUITOUS_LANGUAGE.md`](./UBIQUITOUS_LANGUAGE.md)
- Code should use terms from UBIQUITOUS_LANGUAGE.md exactly (`Folder` for the internal record, `Drive Folder` for the external one, `Ingest` as the verb, `Re-embedding` never "re-indexing", `Tool` only for Agent tools, etc.)

**Two-tier model strategy (confirmed during grilling)**
- GPT-5.4 full: Orchestrator Tool Loop — agentic reasoning, contradiction judgment, synthesis narration
- GPT-5.4 nano: Query Router, `simple`-route answers, ingest-time File Summary + Claims
- Rationale: nano across the board would fail multi-step agentic reasoning; full across the board would make ingest unaffordable

**Build sequence (see SPEC.md §29)**
- **v0.1** — walking skeleton: OAuth + allowlist + session cookie; paste URL → ingest PDFs + Docs only; Voyage embeddings; pgvector only (no BM25); single LLM call with top-K context (no Agent loop, no Router); Conversations + Messages + SSE; page/heading-level Citations + Deep Links; Fly deploy; manual re-ingest.
- **v0.2** — retrieval quality + scope: BM25 + RRF + reranker; Slides/Sheets/Office extractors; Agentic Tool Loop + nano Router; tool-call cap; `traces` table.
- **v0.3** — scale + sync: Drive Changes API polling; content-hash dedup; File Summaries + Claims at ingest; Pooled + Summary Folder Embeddings.
- **v0.4** — advanced: Task mode `/tasks/run` + catalog; `find_contradictions` + `synthesize_themes`; optional Langfuse; retrieval eval gated in CI.
- **v0.5** — polish: skipped-files surface, error UX, usage dashboard, daily Spend Cap enforcement.

**Citation trust posture**
- The Orchestrator must never synthesize a Citation. Every Citation returned to the user must originate from a Tool's structured output. This is load-bearing for the "better citations" must-have in the original prompt and should be enforced at the Tool boundary (Tool outputs carry Citations; Orchestrator text must only reference Citation IDs already emitted by a Tool).

**Model pinning**
- Pin exact model identifiers in `config.py`. When upgrading, bump version, re-run the retrieval eval set and recall@10 gate, and compare `traces` on a fixed replay set before rolling out.
