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
8. **Shutdown:** Use the page-owned UiDispatcher for background UI work. Never create/schedule coroutines after page-loop shutdown. Close/disconnect cancels jobs and stops the retained voice listener; lifecycle event handlers must not depend on a closing executor. Keep cancellable loopback HTTP reads active before response headers as well as during streaming. Do not reintroduce synchronous response.close callbacks on the UI cancellation path.
9. **File Results:** Treat `attached/` as input copies: ordinary edits publish a visible `results/` copy in the same chat workspace. Validate Python before approval without executing it. Normalize escaped line separators only when the original Python is invalid, outside quoted strings/comments and after successful revalidation; reject ambiguous/invalid output. Never globally decode escapes. Every successful file mutation returns a typed FileReceipt tool artifact after exact byte readback. Build file-operation outcomes from these receipts, recheck them before reporting success, and distinguish syntax checking from executing tests. Original-file changes retain current-request attachment, explicit approval, fingerprint and backup requirements.

## Verification & Commands

- **Document formatting:** The two JSON files in `standards/` are partial, non-executable source registries, not full standards or certificates. The desktop «Оформить по ГОСТ» action accepts one DOC/DOCX and produces a reviewed editable project through document_jobs/document_runner and the separately prepared `butuz-documents:local` image. No host converter fallback, automatic downloads or model-generated execution code. Validate bounded exports and the runtime code fingerprint; keep this runtime separate from run_python/run_pytest. Request-owned DocumentApproval shows pages, actual text, warnings, exact path and candidate hash; cancellation, stale jobs and refusal prevent publication. Publish exact approved bytes under results/ with FileReceipt. Preserve technical text, figures, tables, titles, signatures and opaque objects; only recognized pagination caches may change values. Numbered body requirements using Heading 3/4 are not section headings. Never claim full GOST compliance: this profile is partial and preserves original frame geometry. PDF reconstruction and forms from scratch are not implemented. See `docs/gost-formatting.md`.
- **Selected standards and diagrams:** `standards/profiles/eskd_text.json` selects reviewed registry versions/rule IDs and project choices; use `standard_profiles.load_profile`, never merge all PDFs or silently apply unselected/conflicting rules. Include the recipe and selected evidence in the image freshness fingerprint. `document_elements` formats only unambiguously captioned body tables and supported existing pictures. Preserve table data, merges, numbering, crops, relationships and opaque media/OLE bytes; do not redraw diagram elements or connections. Unsupported geometry and missing references become review items. A growing registry is not an implemented bulk PDF ingestion/automatic applicability service.

- Install locked dependencies: `uv sync`
- Check types (flat source layout): `uv run mypy . --exclude '(^tests/|^agent_workspace/|^\.venv/)'` (legacy typing issues remain; report them honestly).
- Run tests: `uv run pytest`
- Run GUI: `uv run python prilozhenie.py`; use `uv run flet run prilozhenie.py` for development with automatic reload.
- Run CLI: `uv run python main.py`
- Check/import storage: `uv run python storage.py` (stop any old app instance before the first migration).
- Start Ollama if not already running: `ollama serve`; inspect installed models with `ollama list`. Do not pull models automatically.

## Release checks
- Run `uv run python doctor.py` for read-only local readiness checks.
- Run `uv run python evaluate_rag.py` for deterministic retrieval CI and add `--live` only for local-model quality checks. Fixtures must be synthetic or explicitly cleared for publication.
- Keep runtime data out of Git; never use `git add .` without reviewing the staged paths.
- Keep the staged progress and validation evidence in `PRODUCTION_PROGRESS.md`.
10. **Sandbox Execution:** run_python/run_pytest execute only through sandbox_runner in a disposable local Docker container using the prebuilt butuz-sandbox:local image (resolved to a local image ID). Never fall back to host Python/shell or auto-pull/install dependencies at runtime. Mount only a filtered read-only chat snapshot; discard container writes. Enforce no network, non-root user, read-only root, dropped capabilities, no-new-privileges, CPU/memory/PID/disk/time/output limits. Report actual ExecutionResult artifacts, including failures and cancellation, separately from syntax checks and write receipts. Preparing the image is an explicit setup step.
