# AGENTS.md — BUTUZ_AI Project Context

## Stack & Environment
- **GUI Framework:** Flet (Python, async/await UI loops).
- **ML / AI Engine:** PyTorch; local LLM inference through **Ollama**, using its OpenAI-compatible endpoint `http://127.0.0.1:11434/v1`.
- **Default LLM:** `qwen2.5:14b`; the GUI may select another locally installed Ollama model. Respect `LLM_MODEL_NAME` from `.env`.
- **Package Manager:** `uv` (use `uv run` for executing Python scripts).
- **Do not switch to LM Studio or another inference provider unless the user explicitly requests it.** Ollama is the intended backend.

## Architecture
- The assistant's application name is **BUTUZIK.AI** and its creator is **Demashov Michail Sergeevich**. Keep this identity consistent across CHAT / SEARCH / AGENT. These are application metadata, not claims about the authorship of the underlying Ollama model.
- Keep the three routes: **CHAT / SEARCH / AGENT**. The explicit agent switch overrides automatic routing.
- Use the selected local LLM for routing, final answers and tool calling. Image attachments are automatically analyzed by a separate local `VISION_MODEL_NAME` worker (default `qwen2.5vl:7b`); pass its observations as untrusted data to the selected LLM. Do not switch the GUI model or require the user to switch it for images. If the selected model is already the configured vision model, direct image input may avoid a redundant second call. Tool calling requires a capable selected model.
- Keep the agent universal: document search, analysis, creating/editing files, and code assistance; do not force every task into a code-edit/test loop.
- SEARCH and AGENT use the same retrieval service. Scope attachment retrieval to the current `chat_id`; `global` uploads are explicitly shared.
- Use **one persistent Chroma client** at `data/chroma/` with collections `knowledge_base` and `attachments`. Preserve parent-child documents.

- Chat history lives in `data/chats.sqlite3` (transactional SQLite WAL). `chats_history.json` is a read-only legacy migration source. Preserve its backup and all optional fields. Use `ChatManager` mutation methods; `chats` returns a detached read snapshot. Use `ChatStore.backup` for live backups, not a raw copy of the main SQLite file.

## Critical Execution Rules
1. **Flet Threading:** All blocking AI/LLM and retrieval work must run via `asyncio.to_thread` or background execution queues/threads, never on the GUI event loop. `SmartRAG.aquery` is the async entry point.
2. **Local Isolation:** No cloud model requests. Route all LLM calls strictly to `http://127.0.0.1:11434/v1`; disable environment proxies, redirects, and cloud tracing. Models must already be available locally; do not download them during runtime.
3. **Type Hints:** Use strict type annotations for new function signatures.
4. **Data Preservation:** Never delete or overwrite original documents or legacy Chroma databases as part of a backend change. Migration reads snapshots, verifies copied records, and retains originals. A knowledge-index rebuild must preserve the attachments collection and create a backup first.
5. **Agent Tools:** Restrict universal-agent file access to a per-chat workspace in `agent_workspace/chats/`; capture attachment permissions and approval callbacks per request. Do not reintroduce global callbacks or registries into SmartRAG. Editing an attached original requires explicit GUI approval. Do not expose arbitrary host Python execution without a separately designed isolation mechanism.
6. **File UX:** In the desktop GUI, every file mutation uses the request-owned approval callback with the exact path and future content. The modal uses buttons, never conversational yes/no loops. Rejection, timeout, stale jobs and cancellation must prevent the pending write. Keep results in existing chat workspaces; expose them through «Файлы чата», reveal-in-folder and an explicit Save As copy. Do not move existing output or automatically write to Desktop/Documents. Attachment copies stay separate from generated results. CLI workspace writes may run without a GUI callback; originals still require explicit approval.
7. **Visual Progress:** Use request-owned `ActivityEvent` callbacks for work phases; keep progress out of answer text/history. Schedule ordered phase updates on the page event loop and reject callbacks from stale/cancelled jobs. Use local vector artwork in `assets/icons/ui/`, the existing pilot-dog mascot and native Flet animations; do not add perpetual Python animation threads or remote UI assets. Approval and terminal states must stop progress animation.

## Verification & Commands
- Install locked dependencies: `uv sync`
- Check types (flat source layout): `uv run mypy . --exclude '(^tests/|^agent_workspace/|^\.venv/)'` (legacy typing issues remain; report them honestly).
- Run tests: `uv run pytest`
- Run GUI: `uv run flet run prilozhenie.py`
- Run CLI: `uv run python main.py`
- Check/import storage: `uv run python storage.py` (stop any old app instance before the first migration).
- Start Ollama if not already running: `ollama serve`; inspect installed models with `ollama list`. Do not pull models automatically.

## Release checks
- Run `uv run python doctor.py` for read-only local readiness checks.
- Run `uv run python evaluate_rag.py` for deterministic retrieval CI and add `--live` only for local-model quality checks. Fixtures must be synthetic or explicitly cleared for publication.
- Keep runtime data out of Git; never use `git add .` without reviewing the staged paths.
- Keep the staged progress and validation evidence in `PRODUCTION_PROGRESS.md`.
