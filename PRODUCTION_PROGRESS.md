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

## Consistent assistant identity — 2026-11-10

Shared application metadata now identifies the assistant as BUTUZIK.AI and its creator as Demashov Michail Sergeevich. Standalone self-name/creator questions receive exact local responses without model routing, retrieval or tools, including with the agent switch enabled and contradictory old history. Combined requests still reach their normal route with the shared identity instruction in CHAT, SEARCH and AGENT. Application authorship is explicitly distinguished from the underlying model's authorship. File actions, translation requests and questions about other products' creators are not intercepted.

Validation: 109 tests pass. New regression coverage checks the user's colloquial question, creator variants, old-history consistency, both switch states, cancellation, non-interference with file/document tasks and identity instructions in all three generation paths. assistant_identity.py and ai_agent.py pass strict mypy; syntax and whitespace checks pass. UI artwork and layout were not changed in this step.

## Branded desktop UI and request progress — 2026-11-10

The desktop now uses a consistent navy/cyan/amber palette and fifteen original local SVG icons for controls, routes and state. The existing pilot-dog mascot appears in empty chats beside three working CHAT/SEARCH/AGENT example cards. The app title/sidebar match BUTUZIK.AI. Compact chat rows, clearer selected-chat styling and a single toolbar reduce visual noise. Icons retain text labels/tooltips; no remote artwork, new model or image-generation dependency was introduced.

Follow-up: setting Checkbox.label_style alone did not reduce the rendered label on macOS. The caption is now a separate normal-weight 13 px TextButton beside an unlabelled visual checkbox (with its accessibility name retained). Clicking the caption still toggles the same agent flag. The smaller caption was verified in the restarted native GUI; all seven activity/UI tests and the desktop syntax check pass.

Request-owned ActivityEvent callbacks report queueing, thinking, retrieval, file work, vision analysis and answer generation separately from streamed answer text. Ordered page-loop callbacks recheck job/chat ownership. The header shows the selected route after classification; a native progress ring and brief fades/color transitions indicate activity. Approval and terminal states stop the animation. The explicit Stop control cancels the current job and removes its pending bubble. File-approval controls retain their existing permission boundaries. No Python animation loops were added.

Validation: 116 tests pass, including ordered SEARCH phases, real tool-to-file integration with separate progress callbacks, working welcome-card handlers, empty-chat visibility, quiet approval/completion states, cancellation and rejection of stale job updates. Thirteen hardened modules pass strict mypy; SmartRAG passes scoped mypy and desktop syntax checks pass. Native GUI inspection confirmed SVG rendering, the mascot/cards and a successful CHAT example with a return to Ready. Native automation became unreliable during further clicks, so a complete native SEARCH/AGENT/Stop smoke run was not certified. Direct real local Ollama checks passed all three routes: CHAT generation, SEARCH with two sources and AGENT file creation/readback after one approval. Private phase reports remain ignored in eval-results/. Existing documents, history and persistent indexes were not migrated or rebuilt.

## Cancellation and shutdown recovery — 2026-11-10

Fixed late activity/error callbacks attempting to schedule work after the Flet page loop or executor had shut down. Page-owned UiDispatcher now checks lifecycle state before submission and execution, creates coroutine tasks only on the active page loop, drains worker/task results and rejects executor-shutdown races. Async native lifecycle handlers cancel jobs, deny pending file approvals, stop the retained voice listener and destroy the window without relying on a closing executor. The listener is no longer accidentally discarded after startup; wake callbacks are ignored while a request is active or the page is closed. A delete-confirmation dialog no longer cancels generation until deletion is actually confirmed.

Local HTTP cancellation now interrupts socket reads/writes, including the wait before response headers. Socket cancellation callbacks are removed when each I/O operation finishes so a completed request cannot abort a reused connection. UI cancellation no longer synchronously closes an httpx response, and local model calls do not automatically retry an interrupted request. The small httpx/httpcore transport adapter is covered on the locked dependency versions; both libraries are now explicit dependencies without changing their resolved versions. Ordinary desktop startup is documented as `uv run python prilozhenie.py`; the Flet CLI's automatic-reload mode remains available for development.

Validation: 126 tests pass, including real loopback HTTP cancellation before headers and mid-stream, a successful following request, closed-loop/coroutine-factory races, executor shutdown, pending approvals, stale callbacks, window-close dispatch and confirmed-only chat deletion. Sixteen hardened modules pass strict mypy; desktop and voice syntax checks pass. Real local qwen2.5:14b streaming cancelled cleanly in 0.002 seconds in the recorded sample and the next request succeeded. This timing is one observation, not a latency guarantee. Read-only doctor checks reported SQLite/Chroma integrity and local models ready. Native GUI startup, close with Python exit code 0 and reopening were observed; automated native text input remained unreliable, so the Stop-button flow is covered by callback tests plus the separate live Ollama cancellation check rather than a certified complete native click-through. The private live report remains ignored under eval-results/.

The orphaned old Python process without a window was terminated after it ignored normal termination. No documents or indexes were migrated or rebuilt. Already-running native embedding calls still finish their current operation before the cancelled result is discarded; completed atomic file writes are not rolled back.
