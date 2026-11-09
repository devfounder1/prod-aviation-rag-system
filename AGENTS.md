# AGENTS.md — BUTUZ_AI Project Context

## Stack & Environment
- **GUI Framework:** Flet (Python, async/await UI loops).
- **ML / AI Engine:** PyTorch; local LLM inference through **Ollama**, using its OpenAI-compatible endpoint `http://127.0.0.1:11434/v1`.
- **Default LLM:** `qwen2.5:14b`; the GUI may select another locally installed Ollama model. Respect `LLM_MODEL_NAME` from `.env`.
- **Package Manager:** `uv` (use `uv run` for executing Python scripts).
- **Do not switch to LM Studio or another inference provider unless the user explicitly requests it.** Ollama is the intended backend.

## Architecture
- Keep the three routes: **CHAT / SEARCH / AGENT**. The explicit agent switch overrides automatic routing.
- Use one selected local LLM for routing, answers, vision (if supported), and tool calling. Tool calling requires a capable local model.
- Keep the agent universal: document search, analysis, creating/editing files, and code assistance; do not force every task into a code-edit/test loop.
- SEARCH and AGENT use the same retrieval service. Scope attachment retrieval to the current `chat_id`; `global` uploads are explicitly shared.
- Use **one persistent Chroma client** at `data/chroma/` with collections `knowledge_base` and `attachments`. Preserve parent-child documents.

- Chat history lives in `data/chats.sqlite3` (transactional SQLite WAL). `chats_history.json` is a read-only legacy migration source. Preserve its backup and all optional fields. Use `ChatManager` mutation methods; `chats` returns a detached read snapshot. Use `ChatStore.backup` for live backups, not a raw copy of the main SQLite file.

## Critical Execution Rules
1. **Flet Threading:** All blocking AI/LLM and retrieval work must run via `asyncio.to_thread` or background execution queues/threads, never on the GUI event loop. `SmartRAG.aquery` is the async entry point.
2. **Local Isolation:** No cloud model requests. Route all LLM calls strictly to `http://127.0.0.1:11434/v1`; disable environment proxies, redirects, and cloud tracing. Models must already be available locally; do not download them during runtime.
3. **Type Hints:** Use strict type annotations for new function signatures.
4. **Data Preservation:** Never delete or overwrite original documents or legacy Chroma databases as part of a backend change. Migration reads snapshots, verifies copied records, and retains originals. A knowledge-index rebuild must preserve the attachments collection and create a backup first.
5. **Agent Tools:** Restrict file access to the agent workspace. Editing an attached original requires explicit GUI approval. Do not expose arbitrary host Python execution without a separately designed isolation mechanism.

## Verification & Commands
- Install locked dependencies: `uv sync`
- Check types (flat source layout): `uv run mypy . --exclude '(^tests/|^agent_workspace/|^\.venv/)'` (legacy typing issues remain; report them honestly).
- Run tests: `uv run pytest`
- Run GUI: `uv run flet run prilozhenie.py`
- Run CLI: `uv run python main.py`
- Check/import storage: `uv run python storage.py` (stop any old app instance before the first migration).
- Start Ollama if not already running: `ollama serve`; inspect installed models with `ollama list`. Do not pull models automatically.
