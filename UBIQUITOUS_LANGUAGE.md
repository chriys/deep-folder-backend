# Ubiquitous Language

## Drive integration

| Term                 | Definition                                                                                              | Aliases to avoid                          |
| -------------------- | ------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| **Drive Folder**     | The external Google Drive folder identified by a Drive folder ID that a user pastes in as a link.       | Google folder, source folder              |
| **Drive File**       | An individual file living in Google Drive (Google Doc, PDF, Slides, Sheets, Office, txt/md).            | Document, object                          |
| **Folder URL**       | Any Drive URL shape that resolves to a Drive Folder ID after parsing.                                   | Folder link, share URL                    |
| **Drive Changes**    | The delta stream returned by the Drive Changes API, scoped by `start_page_token`.                       | Drive diff, updates                       |
| **Deep Link**        | A URL pointing to a specific location inside a Drive File (page, heading, slide, sheet range).          | Anchor URL, jump link                     |
| **Anchor ID**        | A Google-native identifier (heading ID, slide object ID, sheet gid) used to build a Deep Link.          | Bookmark, target                          |

## Ingestion

| Term             | Definition                                                                                                          | Aliases to avoid                       |
| ---------------- | ------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| **Ingest**       | The pipeline that turns a Drive Folder's contents into queryable Chunks, Embeddings, and File Summaries.            | Index, import, crawl                   |
| **Folder**       | Our internal record of an ingested Drive Folder, owning Files, Chunks, and Folder Embeddings.                       | Collection, workspace                  |
| **File**         | Our internal record of an ingested Drive File, owning Chunks, a File Summary, and a Claims list.                    | Doc record, document                   |
| **Extractor**    | A per-type component that turns a Drive File into structured text with Primary Unit boundaries.                     | Parser, reader                         |
| **Skipped File** | A Drive File whose type is unsupported in v1 (images, audio, video, arbitrary binaries).                            | Failed file, ignored file              |

## Chunks & citations

| Term                  | Definition                                                                                                                          | Aliases to avoid                |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- |
| **Chunk**             | A retrievable text span produced from a File, bounded by a Primary Unit and optionally split into ≤512-token pieces.                | Passage, segment, fragment      |
| **Primary Unit**      | The natural structural boundary a Chunk lives inside: PDF page, slide, sheet range, or heading section.                             | Structural unit, section        |
| **Sub-index**         | The zero-based position of a Chunk within its Primary Unit when the unit is split.                                                  | Chunk number                    |
| **Content Hash**      | SHA-256 of Chunk text; unchanged hashes skip re-embedding during Sync.                                                              | Text hash, checksum             |
| **Citation**          | The structured metadata object identifying the source of an agent claim (file, Primary Unit, quote, Deep Link).                     | Reference, source               |
| **Quote**             | The exact text span the agent relied on, always returned inside a Citation.                                                         | Snippet, excerpt                |

## Retrieval

| Term                        | Definition                                                                                                           | Aliases to avoid                              |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| **Chunk Embedding**         | The Voyage-produced vector for a single Chunk, stored in pgvector.                                                   | Vector, encoding                              |
| **Pooled Folder Embedding** | The mean of all Chunk Embeddings in a Folder; the folder's semantic centroid.                                        | Folder vector, centroid                       |
| **Summary Folder Embedding**| The embedding of an LLM-written folder summary, used for "what is this folder about" queries.                        | —                                             |
| **Vector Search**           | Nearest-neighbor search over Chunk Embeddings.                                                                       | Semantic search                               |
| **Keyword Search**          | Full-text search using Postgres `tsvector` + `ts_rank_cd`, the BM25-style leg of Hybrid Search.                      | BM25, FTS                                     |
| **Hybrid Search**           | The unified retrieval step: Vector Search ∪ Keyword Search → RRF → Reranker → top 10–15.                             | Search (ambiguous), combined search           |
| **RRF**                     | Reciprocal Rank Fusion (k=60) used to merge Vector and Keyword result lists.                                         | Fusion                                        |
| **Reranker**                | The Voyage cross-encoder pass that re-scores the top-50 fused Chunks before returning results to the Agent.          | Re-scorer                                     |

## Agent & conversation

| Term                | Definition                                                                                                                | Aliases to avoid                       |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| **Agent**           | The conversational entity that answers user messages using Tools; drives the Tool Loop.                                   | Bot, assistant, AI                     |
| **Orchestrator**    | The specific LLM (GPT-5.4 full) that runs the Agent's Tool Loop.                                                          | Driver, brain                          |
| **Query Router**    | The nano-tier classifier that labels every incoming user Message as `simple`, `complex`, or `task` before dispatch.       | Classifier, intent detector            |
| **Tool**            | A named, typed function the Orchestrator can call during a Tool Loop (e.g. `search`, `find_contradictions`).              | Function, capability                   |
| **Tool Loop**       | The iterative plan → call → interpret cycle, hard-capped at 15 Tool calls per Message.                                    | Agent loop, reasoning loop             |
| **Conversation**    | A thread bound to exactly one Folder, holding an ordered list of Messages.                                                | Chat, session                          |
| **Message**         | One user or assistant turn inside a Conversation, carrying content, Tool Calls, and Citations.                            | Turn, post                             |
| **File Summary**    | A 300–500 token nano-generated structured summary of a File, produced at Ingest time.                                     | Abstract, description                  |
| **Claim**           | A discrete factual assertion extracted from a File at Ingest time, citation-attached; the substrate for contradiction.    | Fact, statement, assertion             |
| **Contradiction**   | A pair of Claims across different Files that are semantically close but opposing, surfaced by the server-side Tool.       | Conflict, disagreement                 |
| **Theme**           | A cluster label produced by `synthesize_themes` when grouping File Summaries.                                             | Topic, category                        |

## Task mode

| Term             | Definition                                                                                                            | Aliases to avoid                     |
| ---------------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| **Task**         | A user-facing structured operation (`extract_action_items`, `summarize`, `compare`, `extract_entities`) run against a Folder. | Action, command                      |
| **Task Catalog** | The fixed enumerated set of Task types with their Pydantic parameter and output schemas.                              | Task list, task registry             |
| **Task Run**     | A single invocation of a Task against specific inputs, streamed back over SSE.                                        | Task execution, task instance        |

## Sync

| Term                 | Definition                                                                                                         | Aliases to avoid                |
| -------------------- | ------------------------------------------------------------------------------------------------------------------ | ------------------------------- |
| **Sync**             | The periodic process that applies Drive Changes to an ingested Folder and re-embeds changed Chunks.                | Refresh, update                 |
| **Sync Tick**        | One scheduled execution of Sync (every 2–5 minutes per Folder).                                                    | Poll, pass                      |
| **Manual Sync**      | A user-triggered Sync via `POST /folders/{id}/sync`, outside the scheduled cadence.                                | Force sync                      |
| **Re-embedding**     | Generating a new Chunk Embedding because the Chunk's Content Hash changed.                                         | Re-indexing, re-encoding        |

## Background infrastructure

| Term            | Definition                                                                                                          | Aliases to avoid                 |
| --------------- | ------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| **Job**         | A unit of deferred work in the Postgres `jobs` table (Ingest Folder, Sync Folder, Generate File Summary, etc.).     | Background task, queue item      |
| **Worker**      | The process that dequeues Jobs via `SELECT ... FOR UPDATE SKIP LOCKED` and executes them.                           | Runner, consumer                 |
| **Scheduler**   | The APScheduler process that enqueues recurring Jobs (Sync Ticks).                                                  | Cron, timer                      |
| **Trace**       | A row in the `traces` table recording one Orchestrator LLM call or Tool Call for replay and diffing.                | Log entry, span                  |
| **Usage Row**   | A row in the `usage` table recording cost and tokens for one LLM or embedding call.                                 | Billing record, cost log         |
| **Spend Cap**   | The configurable daily USD limit that hard-stops new LLM/embedding calls once exceeded.                             | Budget, quota                    |
| **Allowlist**  | The `ALLOWED_EMAILS` set that gates which Google accounts can authenticate and use the API.                         | Whitelist                        |

## Relationships

- A **User** authenticates once via Google OAuth; that same identity is enforced through an **Allowlist** for every subsequent API call.
- A **Folder** is created by ingesting exactly one **Drive Folder**.
- A **Folder** owns one **Pooled Folder Embedding** *and* one **Summary Folder Embedding**.
- A **File** belongs to exactly one **Folder**, produces one **File Summary** and many **Claims**, and is split into many **Chunks**.
- A **Chunk** lives inside exactly one **Primary Unit** and has exactly one **Chunk Embedding**.
- A **Citation** references exactly one **Chunk** and carries the **Quote** + **Deep Link**.
- A **Conversation** belongs to exactly one **Folder** and holds many ordered **Messages**.
- A **Message** produced by the **Agent** may emit zero or more **Tool Calls** and zero or more **Citations**.
- The **Query Router** classifies every user **Message** into `simple | complex | task`; `complex` and `task` engage the **Tool Loop**, `simple` bypasses it.
- A **Task Run** executes one **Task** (from the **Task Catalog**) against one **Folder** and streams a structured result.
- A **Sync Tick** produces a batch of **Jobs** for changed **Files**; each Job may cause **Re-embedding** of affected **Chunks**.
- A **Contradiction** is a pair of **Claims** across two different **Files** inside the same **Folder**.

## Example dialogue

> **Dev:** "When a user pastes a **Folder URL**, what's the boundary between **Ingest** and **Sync**?"

> **Domain expert:** "**Ingest** is the first-time crawl: parse the URL, create the **Folder**, pull every **Drive File** below the depth limit, run the **Extractors**, produce **Chunks**, **Chunk Embeddings**, **File Summaries**, and **Claims**. **Sync** is everything after — a **Sync Tick** pulls **Drive Changes** and enqueues **Jobs** only for **Files** whose **Content Hashes** moved."

> **Dev:** "And when the user asks 'where do these two reports disagree?' — does the **Agent** do that directly?"

> **Domain expert:** "No. The **Query Router** tags it `complex`, the **Orchestrator** enters a **Tool Loop**, and it calls the `find_contradictions` **Tool**. That **Tool** server-side searches **Claim** pairs across **Files** and returns candidates with **Citations**. The **Orchestrator** judges and narrates — it never eyeballs raw **Chunks** for that job."

> **Dev:** "What about 'extract all action items' — same path?"

> **Domain expert:** "Different path. That's a **Task**. The user can hit `POST /tasks/run` directly with `task_type: extract_action_items`, producing a **Task Run** with a structured Pydantic output. Or, inside a **Conversation**, the **Orchestrator** can invoke the same **Task** via the `run_task` **Tool** — both paths share the same handler."

> **Dev:** "If I edit one paragraph in a 200-page PDF, what happens at the next **Sync Tick**?"

> **Domain expert:** "**Drive Changes** reports the **File** modified. A **Job** re-runs the **Extractor** and rebuilds **Chunks**. Each new **Chunk**'s **Content Hash** is compared to the stored set — **Re-embedding** fires only for the one or two **Chunks** whose text actually changed. The **File Summary** and **Claims** regenerate, and the **Pooled Folder Embedding** is recomputed cheaply from the updated **Chunk Embeddings**."

## Flagged ambiguities

- **"Folder"** is overloaded between *Drive Folder* (the external Google entity) and *Folder* (our internal ingested record). Canonical rule: the external thing is always **Drive Folder**; unqualified **Folder** always means the internal record. Same convention for **Drive File** vs **File**.

- **"Task"** clashes hard between (a) a user-facing structured operation served by `/tasks/run`, and (b) a generic "background task" in a job queue. Canonical rule: user-facing = **Task**; background queue item = **Job**. Never say "background task" — say **Job**.

- **"Index"** was used in the original prompt ("semantic folder indexing") as a verb for ingestion. Canonical rule: the verb is **Ingest**; the noun is **Folder** (or **Chunk**, **Embedding**). "Index" is avoided because it also evokes a database index.

- **"Embedding"** is used for three distinct artifacts: **Chunk Embedding**, **Pooled Folder Embedding**, **Summary Folder Embedding**. Never say "folder embedding" without the qualifier — it's ambiguous by one-to-two.

- **"Tool"** is agent-specific here, meaning a function the **Orchestrator** can call. It does *not* mean "CLI tool" or "internal utility." When speaking of code modules (e.g. the `drive/` module), use "component" or "module," never "tool."

- **"Summary"** has two distinct senses: **File Summary** (an Ingest-time artifact per File, used by retrieval) and the output of a **Task** like `summarize` (a user-facing deliverable). Canonical rule: always qualify — **File Summary** for the ingest artifact, **Task Run** (of task_type `summarize`) for the user-facing one.

- **"Router"** could clash with FastAPI `APIRouter` code modules. Canonical rule: domain term is always **Query Router** (never just "router"); the FastAPI objects are "routes" / "routers" and don't appear in domain conversation.

- **"Search"** without qualifier is ambiguous between **Vector Search**, **Keyword Search**, and **Hybrid Search**. In design discussion, always qualify. In tool names, `search` is always **Hybrid Search** (the only kind the **Agent** invokes directly).

- **"Re-embed" vs "re-index"**: only **Re-embedding** is canonical. "Re-indexing" is banned — it implies the whole pipeline reruns, which it doesn't; only changed **Chunks** are affected.

- **"User"** means the single authenticated human identity gated by the **Allowlist**. It is *not* a Drive concept and is *not* a Google-account synonym beyond "the person behind the allowed email." v1 has exactly one **User**; the term exists to keep the data model shape correct.
