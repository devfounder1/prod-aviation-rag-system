# Production hardening progress

The application remains local: Ollama, CHAT/SEARCH/AGENT, two collections in one Chroma, SQLite chat history.

- [x] 0. Repository hygiene: exclude private runtime data; publish source branch.
- [x] 1. Router: constrained intent output, validation and safe fallback.
- [x] 2. Jobs: per-request cancellation and stale UI callback protection.
- [x] 3. Tools: per-chat workspace and per-request attachment/approval context.
- [x] 4. RAG evaluation: reproducible corpus, expected sources and abstention metrics.
- [x] 5. Release checks: offline diagnostics, log rotation, CI and recovery instructions.

Passing these checks does not certify model answer correctness or safe execution of arbitrary code. Host Python execution remains disabled for the universal agent.

Router validation: 34 tests pass. Live Ollama classified the previous Reply-only failure as CHAT, a documentation question as SEARCH and file creation as AGENT.

Jobs: request-owned tokens close active synchronous HTTP responses on cancel. One inference/retrieval slot per desktop process; queued cancelled jobs exit. GUI callbacks re-check job identity when executed. Running native embedding operations finish their current call, but their cancelled results cannot start generation or mutate the UI.

Tool isolation: 42 tests pass. Universal-agent file tools now capture a chat workspace and a request-local original-file registry/approval callback. Tests cover parallel identical filenames, symlink/traversal rejection, cancellation during approval and external edits. Legacy agent_tools.py is retained for old standalone scripts but is not exposed by SmartRAG.

RAG quality: the five fictional cases passed with real local embeddings, reranker and qwen2.5:14b. Source recall@1, expected-fact accuracy, document-name citation accuracy and abstention accuracy were 1.0 on this small fixture. Deterministic CI embeddings validate retrieval plumbing only. A representative expert-reviewed aviation dataset is still needed before claiming domain accuracy.

Release checks: 47 tests pass in the project and in a fresh offline-installed macOS/Python 3.13 environment; six hardened modules pass strict mypy. doctor.py reports local Ollama/model caches and both databases ready. Live checks passed for the Reply-only regression, interruption of an HTTP generation stream and creation/readback of a file in a chat-specific workspace. Local log rotation, source-only CI and recovery instructions are included.

Final GUI launch was observed, but the native automation input/window channel was unreliable during the repeat smoke test. Do not count that final GUI pass as completed; the previous pre-hardening GUI smoke test is not proof of the new boundaries. New boundaries are covered by unit/integration tests and direct live Ollama checks. Additional platform UI testing, expert-reviewed real-domain evaluation and long-running load tests remain release gates.

Privacy: runtime directories were removed from the branch tip without deleting existing local files. They still exist in older repository commits; this work does not rewrite history. A checksum comparison verified 5,234 original document/legacy-index files unchanged.

## Image-input correction — 2026-11-10

Reproduced Ollama HTTP 400: qwen2.5:14b rejected multimodal requests. Added the already-installed qwen2.5vl:7b to the GUI selector, actionable capability errors and request-owned attachment restoration for retry. Plain image questions bypass unrelated RAG retrieval; explicit document references still route normally. Agent requests now receive image parts instead of silently dropping them. The selected model remains unchanged unless the user changes it.

Validation: 54 tests pass; vision.py passes strict mypy; smart_rag.py and ai_agent.py pass scoped mypy. A real local qwen2.5vl:7b request described the repository icon (shield, wings, aircraft and a dog wearing goggles) and returned icon.png as its source. The text-model failure was also exercised against real Ollama. No model downloads or cloud inference were used.

## Automatic local vision pipeline — 2026-11-10

Image attachments now use an internal local analyzer (`VISION_MODEL_NAME=qwen2.5vl:7b`, bounded by `VISION_MAX_TOKENS=512`). Its observations are passed as untrusted text to the selected chat/tool model. No GUI model switch is required; raw pixels do not reach a text-only primary model. An explicitly selected model matching the configured vision worker can still use direct image input to avoid duplicate work. Empty, unavailable or cancelled analysis does not allow the primary model to guess an answer; image-analysis failures retain the attachment for retry.

Validation: 59 tests pass; vision.py passes strict mypy and smart_rag.py/doctor.py pass scoped mypy. Read-only diagnostics report both local models available. Real Ollama checks completed with qwen2.5:14b remaining selected: first an image-description answer, then an agent-generated/read-back text report about the repository icon in an isolated test chat. No cloud inference, automatic model downloads or document migration were used. Textual visual observations can lose detail; expert validation remains necessary for critical interpretation.

## Technical-search and response-depth regression — 2026-11-10

Reproduced a valid but incorrect CHAT classification for an equipment question while the relevant documents remained available. Strong local technical identifiers/signals now select SEARCH before model classification; explicit file-generation/edit requests remain eligible for AGENT. The model router remains responsible for other intents.

Restored a detailed source-grounded technical-answer policy: a direct answer, explanatory sections, conditions/parameters and document citations, with explicit user requests for brevity taking precedence. Navigation-only documents are excluded unless the user asks about contents/structure. General uploaded fragments must match a requested technical identifier before being mixed into an equipment-specific answer. The primary hybrid retriever remains semantic. A conservative output pass removes parenthesized acronym expansions absent from the provided source text; this is not complete factual validation.

Validation: 75 tests pass, including the equipment/PPS routes, actual SEARCH invocation, navigation access/filtering, unrelated-upload exclusion and streamed/final acronym cleanup. New policy modules pass strict mypy; smart_rag.py passes scoped mypy. Real local checks returned both technical answers with relevant document sources and several explanatory sections. The five-case fictional live RAG benchmark still passed all four metrics. Private answer reports remain under ignored eval-results/ and are not committed. No reindexing or document migration was performed. Expert review of technical interpretations remains required.

## Interactive file approvals and accessible output — 2026-11-10

Desktop file mutations now call a request-owned approval callback before writing: the modal shows create/replace/original-edit intent, the full path and proposed content, with Allow Write/Cancel buttons. The model is instructed to use tools immediately for explicit file requests and to leave approval to the UI, including when older history contains conversational permission requests. Rejected paths cannot reopen confirmation within that request. Timeout, dismissal, cancellation and stale chat/job ownership deny the pending write. Workspace changes while awaiting approval are detected. Attached-original backup and fingerprint checks remain in place; CLI workspace writes remain available without a GUI callback.

A permanent «Файлы чата» button lists existing and new per-chat results, excluding attachment copies, hidden temporary files and symlink escapes. Users can reveal a file/open its folder or export a byte-preserving copy through native Save As. Exports require an explicit user-selected destination outside internal application folders and do not move the original. Existing workspace locations and user documents remain unchanged.

Validation: 85 tests pass. Ten hardened modules, including agent_files_ui.py and file_tools.py, pass strict mypy; desktop integration syntax checks pass. Tests exercise real Flet modal button callbacks controlling a blocked worker's write, approval/rejection, cancellation, timeout, stale requests, DOCX creation, external workspace edits and scoped export/cancel. Two real qwen2.5:14b checks passed: creation with exactly one approval despite old yes/no history; rejection with exactly one approval and no output file. Private reports remain ignored in eval-results/.

The updated desktop was restarted. Native GUI inspection confirmed «Файлы чата» and the existing mihail_info.txt from the user's screenshot. Native input/screenshot updates were unreliable during further automation; the full native Save As and modal-click creation flows were not certified end to end. Their callback/integration behavior is covered by tests. No document/index migration or output relocation was performed.
