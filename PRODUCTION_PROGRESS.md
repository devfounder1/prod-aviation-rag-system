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

## Visible attachment edits and verified file outcomes — 2026-11-10

Reproduced the reported first attempt from the existing workspace: the changed Python file was under hidden attached/, contained ten literal backslash-n separators and failed Python compilation. The second root-level updated file was visible and syntactically valid. No existing user file was rewritten during diagnosis.

Ordinary write/append/line-replacement tools now publish edits of attached inputs under visible results/ in the same chat workspace. Input copies and originals stay unchanged; original editing remains a separate explicitly approved current-request operation. Python output is validated before approval without execution. A same-length tokenizer shadow identifies protected strings, f-strings and comments; only unambiguous escaped separators outside those spans are repaired, only when the original is invalid, and the repaired source must compile. Valid code and non-Python text are unchanged. Ambiguous/invalid proposals are rejected before the modal. Python append and line-replacement boundaries preserve statement separation.

File mutation tools now return typed FileReceipt artifacts after exact byte readback. The agent invokes full tool calls so these artifacts survive the tool loop, rechecks the final file fingerprint and generates file-operation outcomes from verified receipts instead of a model-authored success claim. Rejection stops the action; validation failures can be corrected within the same request. A read-only check_python_syntax tool is available, with explicit wording that code/tests have not run. This does not add host Python execution or promise functional correctness.

Validation: 139 tests pass and nineteen hardened modules pass strict mypy; syntax/whitespace checks pass. Regressions cover attached append/write/line replacement, visible output, one approval, protected string/raw-string/f-string escapes, ambiguous and invalid syntax, no user-code execution, refusal, failed writes, changed-file detection and repair within one agent request. A real local qwen2.5:14b request added ten HELLO WORLD outputs to a synthetic NumPy attachment after one approval; results/lesson_publish_input.py was visible, syntactically valid and statically matched the requested repetition count. Original and input-copy checksums were unchanged. Private reports remain ignored under eval-results/. The application was restarted with the new implementation; existing user documents, results and persistent indexes were preserved.

## Local sandbox execution — 2026-11-10

Added run_python/run_pytest tools backed exclusively by a disposable local Docker container. The selected local Ollama agent receives actual ExecutionResult artifacts; final execution summaries preserve stdout/stderr, exit code, duration and errors rather than model-authored test claims. File write receipts remain independent and do not contradict a subsequent execution result. Missing runtime/image fails closed without host execution or runtime downloads.

Only a filtered per-chat snapshot is mounted, read-only. Container writes use disposable tmpfs. Network is disabled; the container runs as UID 65534 with read-only root, dropped capabilities and no-new-privileges, 1 CPU, 512 MB memory/swap ceiling, 64 PIDs, bounded tmpfs, 30-second execution deadline and 64 KB combined output. The code cannot install dependencies from the network. Preparing the pinned-base Python/NumPy/pytest image is a separate explicit build step. Docker Desktop and the prepared image are available on this machine.

Validation: 142 offline tests pass, with the live-container test skipped by default. All four sandbox tests pass when enabled against the real local image. Checks include NumPy, successful/failing pytest, network denial, immutable input, discarded output files, infinite-loop timeout and output flood limits. Three modified runtime modules pass strict mypy. A real qwen2.5:14b request selected run_pytest and returned the actual `1 passed`, exit 0 result. Existing documents and host code were not executed or overwritten. Runtime files/reports remain ignored.

## GOST document formatting requirements — 2026-11-11

Reviewed the supplied 42-page ГОСТ Р 2.105-2019 copy (2024 edition with amendments and correction). Added an initial, non-executable registry of 20 rules with source SHA-256, one-based PDF page references, clause numbers, applicability, normative strength, exceptions and intended validation methods. Visually reviewed informative examples А.1, А.2 and Б.1. The profile distinguishes frame clearance from sheet margins and recommendations from mandatory requirements; no universal Times New Roman/14 pt policy was invented.

The implementation note defines editable DOCX as the intended output, local processing through existing AGENT, content preservation, controlled rendering, approval and FileReceipt integration. This is requirements groundwork only: no formatter, PDF reconstruction or GUI flow was added. A real source document and applicable form/template dependencies are still required. Original PDF and runtime extraction/render files were not added to the repository; existing documents, indexes and outputs were untouched.

Validation: JSON parses successfully; all 20 rule IDs are unique, every cited clause is present on its declared PDF pages, and source SHA-256/page count match. Whitespace checks pass. These checks verify registry provenance and structure, not normative completeness or output conformance. No runtime code changed; the application test suite was not rerun for this documentation-only step.

## First GOST source-document pilot and structural inventory — 2026-11-11

Received ГОСТ Р 2.104-2023 (23-page supplied copy, September 2024 edition with corrections) and a real source in binary DOC format. Added 12 partial requirement records with source hash, clauses and PDF pages; visually inspected forms 2 and 2а and their dimension annotations. Updated the earlier registry and implementation note to reflect the received dependency and the distinction between a title page and the first numbered textual sheet. Neither registry is complete or executable.

Converted a copy of the DOC locally with the bundled prepared LibreOffice for diagnosis. Both DOC/DOCX renders have 23 pages, but layout and first-sheet title-block defects remain; experimental rotation patches failed visual review and were not released as finished output. The converter's rendering of the original DOC already exhibits title-block issues, and no independent Word-rendered reference was available. No full conformance claim, user-facing formatter or GUI integration was added. The original source hash is unchanged; all private sources, renders, experimental files and detailed review stay under ignored eval-results/.

Added document_inspection.py, a separate read-only DOCX inventory. It snapshots bounded input bytes, inventories sections/parts/fonts/fields, hashes text and binary parts, counts alternate representations once, flags opaque objects and external relationships without executing/resolving them, rejects duplicate parts/DTD/oversized packages, and creates new reports without overwriting existing files. Reports omit document prose and explicitly do not assess conformance. The pilot inventory identified three sections, ten tables, 39 textboxes, eight image parts, one embedded object and PAGE/TOC fields; numbered body requirements also use heading styles, so blanket style rewriting would be incorrect.

Validation: four new synthetic inventory tests pass, including source preservation, privacy, fallback preservation, external-link non-resolution, legacy-format rejection and ambiguous XML/package rejection. Strict mypy passes for the new module. Full suite: 144 passed, one live-container test skipped, and two loopback tests initially blocked by environment socket permissions; rerunning those two with local socket access passed (146 passing tests in total across the runs). Source hashes, page counts and all 12 clause references match the supplied standard. Unrelated user deletion remains untouched.

## Reviewed DOC/DOCX formatting in the desktop — 2026-11-11

Added «Оформить по ГОСТ» for one pending DOC/DOCX, independent of the agent checkbox and selected Ollama model. This deterministic AGENT action uses the existing request/job/activity lifecycle, then a request-owned modal with paged PNG preview, actual OOXML text, limitations, future path, byte count and SHA-256. Acknowledgment and an explicit Save button approve one immutable candidate. Refusal, stale ownership, changed input, timeout and cancellation prevent publication. Exact bytes are atomically written under the current chat's results/ and re-read for FileReceipt; output remains accessible through «Файлы чата»/Save As. Fixed the picker to close its captured dialog rather than search page.overlay, which does not own Page.open dialogs in Flet 0.28. The application was restarted with this fix.

The partial formatter adjusts known section/subsection roles and selected prose spacing/indentation, preserves numbered Heading 3/4 body requirements, and excludes titles/contents/appendices from blanket paragraph formatting. Existing frame coordinates, prose, table data, signatures, images and embedded objects are preserved. Narrow vertical stamp labels now contain editable rotated cells inside their original textboxes; dates and two-digit PAGE boxes fit. Unambiguous total-page boxes become NUMPAGES, and TOC caches are checked by bookmarks against rendered headings with bounded re-rendering. This does not implement every registry rule, reconstruct PDFs/scans, generate forms from scratch or certify all GOST geometry/metadata requirements. Complex table continuations and cross-renderer layout differences remain review items.

Prepared the separate butuz-documents:local Docker image. The build context is an allowlist of code only. Runtime resolves a local image ID, uses no network, no root/capabilities/privilege escalation, read-only root/input, bounded tmpfs/CPU/memory/PID/file/output/time limits, and fixed converter code. A fixed in-container tar command exports only named, bounded artifacts; no host converter fallback or arbitrary host execution. The caller validates paths/types/counts/PNG dimensions/OOXML and code fingerprint, and always removes the container. The existing Python execution image and its discard-writes policy remain separate. Direct lxml dependency and lock metadata were updated with uv; CI includes the new modules.

Validation: 161 tests pass, with two prepared-runtime tests skipped by default. The new live document-image test passes separately. Real cancellation returned in 1.3 seconds. Eight document/file modules pass strict mypy with silent legacy imports; desktop/worker syntax checks pass. On the user's binary DOC, the pipeline produced a 26-page editable project, corrected the displayed stamp labels/dates/two-digit pages, retained the diagram with its caption, and matched every TOC target in its runtime preview. Native GUI verification completed attachment, action, preview paging, warnings, acknowledgment, Save and visible result in the file panel. Published SHA-256 matches the candidate shown in the modal; the original DOC hash and all nine image/OLE binary hashes match the baseline. A separate bundled-renderer review exposed differences in complex table continuations/pagination; this is recorded as a limitation, and the output is a reviewed project rather than a final compliance certificate. Private examples, reports and renders remain ignored; original indexes/documents and unrelated user edits were not migrated or removed.

## Selected GOST profile, tables and existing diagrams — 2026-11-12

Moved numerical project choices into standards/profiles/eskd_text.json. The typed loader reads only the recipe and its two selected evidence registries, verifies edition metadata and rule IDs, rejects duplicate keys, unknown parameters and unsupported/partial rule selections. Version 1 is one reviewed recipe, not an interpreter for arbitrary combinations of standards. Its sources and parameters are included in the host/container fingerprint. A test adds 120 unrelated malformed registry files and verifies they are never loaded. This is a foundation for a larger library; bulk PDF ingestion, visual-rule extraction, conflict resolution and automatic profile selection are not implemented. Ollama, routing, Chroma and original indexes remain unchanged.

Added conservative formatting of captioned body tables: section-aware width limits, preserved grid proportions and cell merges, contiguous repeated header groups including vertical merge continuations, explicit cell padding and paragraph layout, non-clipping row-height rules, short-row protection and splitting of oversized prose rows. A short final note stays with the preceding record. Explicitly labelled continuation parts start on a new page. Title/signature forms, stamp tables, nested/floating tables and ambiguous grids are excluded from ordinary table normalization. Unsupported cases and uncertain references appear in the review report.

Existing captioned pictures are centered and scaled down proportionally to fit their section with existing notes and caption. Supported simple floating pictures join the text flow; a drawing anchored to an appendix heading can move to a separate paragraph without changing text order. Image crops, relationships and all media/OLE payloads are preserved. Complex groups and opaque objects are not redrawn or executed; numbering and missing references are never invented.

Validation before publication: full suite 173 passed, two prepared-runtime tests skipped by default; the real document-runtime test passed separately. The complete CI strict-type command passes for 28 modules with silent imported legacy modules. Desktop/worker syntax and diff whitespace checks pass. The local document image was rebuilt explicitly and its fingerprint verified by the live test. The private source-document run processed seven tables and one diagram, produced a 28-page preview with every TOC target found, preserved the original source hash and the multiset of all nine media/OLE hashes. A legacy converter may rename an EMF part to .wmf without changing its bytes, so cross-converter comparisons use hashes rather than filenames. Structural and targeted visual reviews confirm the supported layout changes; earlier GUI approval checks cover the same publication path, but the latest profile has not received a new end-to-end GUI save verification.

Known review items remain: manual table parts can leave sparsely populated continuation pages; pagination differs between the prepared runtime and the bundled macOS renderer; some legacy vector diagram labels render with font-spacing defects despite unchanged image bytes. The result is an editable project for human review, not certified final layout. Private previews and source documents stay ignored. The unrelated local deletion of ooopp.py is excluded from the release commit. The running desktop needs a restart to load the updated Python modules.

Publication: committed the reviewed document-formatting stage as 4178872 and pushed it to origin/release. Renamed the working branch to release, without a codex/ prefix, as explicitly requested. No open pull request referenced the old head branch. The old remote name codex/production-hardening was removed only after verifying the new remote head; an exact expected-head lease protected against deleting concurrent work. Main was not modified. AGENTS.md records the release branch and the instruction to commit/push reviewed stages while excluding private data and unrelated changes.

## Reflow table continuations and repair legacy diagram presentation — 2026-11-12

Diagnosed interacting pagination causes in the supplied example: an imported manual page break plus pageBreakBefore at the same continuation boundary, and Heading 3/4 styles carrying keepNext/keepLines into ordinary numbered requirements. Known main prose now reflows without obsolete manual pagination; a break inside text becomes a line break rather than concatenating words. Numbered requirements can split normally. Section and appendix starts remain explicit, duplicate boundary breaks are coalesced, and Word section properties/title material remain intact.

Recognized manual parts of the same numbered table now flow into available space when there is no intervening prose, drawing, field or section boundary. The existing continuation caption becomes a borderless row grouped with the repeating header. A minimal separator keeps the two editable table structures distinct. No captions, repeated original headers, values or merges are deleted; the exact ordered text/instruction guard still passes. Unsupported boundaries retain the conservative layout and a review warning. This removes the previous forced almost-empty pages between table parts while retaining normal free space before a new section/appendix.

Added metafile_layout.py for a tightly bounded legacy EMF subset with the unavailable GOST font. It validates record sizes/counts, object/font selections, Unicode text and DX offsets/options, rejects unsupported transforms/glyph indexes/rotations, and creates a derived display part using the locally supplied Liberation Sans font and natural spacing. Only font name/average width and spacing-pointer fields change; original text strings, drawing records and connection geometry remain unchanged. The original EMF/media/OLE parts and original relationships stay byte-identical, with a new image relationship for presentation. The substitution is disclosed in approval warnings; unsupported files stay original with a review warning. The module is included in the image allowlist/fingerprint and strict CI checks.

Validation: full suite 186 passed, three optional prepared-runtime tests skipped by default. Both live document tests pass separately, including a synthetic continuation with multiple manual/property breaks that must render as one page. Strict mypy passes for all 29 checked modules. The rebuilt local image processed the retained byte-identical legacy DOC copy: 24 pages versus the previous 28, seven supported tables and one repaired diagram, zero unresolved TOC targets. The external source drive was unavailable; the retained source copy matches the recorded original SHA-256 and remained unchanged. All nine original media/OLE hashes are retained, plus one derived presentation part. Rendered the exact runtime DOCX with the bundled renderer and visually reviewed all 24 pages; table continuations no longer have empty intervening pages, the appendix table fits its own page, and diagram words are readable without the previous letter collisions. Private files/renders remain ignored and out of Git. Ordinary free space remains before explicit new sections/appendices; font substitution does not reproduce the exact original GOST typeface or certify full compliance.
## 2026-11-13 — Measured table continuations, paragraph spacing and frame work areas

Follow-up visual review corrected a limitation of the previous stage: putting an
existing continuation label into a repeated header did not label automatic
continuations of the first physical table. Added `table_pagination` to the fixed
local document runtime and its image allowlist, freshness fingerprint and CI type
checks. It merges only proven adjacent same-number manual parts with identical
header text/merges, replaces duplicate furniture, and preserves original data-row
subtrees, values, numbering and merges. Disposable probe copies measure row rules
in the rendered PDF; no probe IDs or guide lines enter the delivered DOCX. Tables
are processed in document order with a fresh render after each split, then every
supported part is checked to occupy one page. Explicit editable continuation
captions and copied headers are added at measured page boundaries. Unknown or
complex geometry is reported for review; ambiguous/unstable measurements fail
without publication. Manual edits in Word can require repagination and review.

Main prose remains at **1.5 line spacing**. Old before/after/autospacing attributes,
grid snapping and inherited paragraph keeps are cleared instead of reducing that
line spacing. The first main section and appendices keep their page starts;
subsequent main sections flow. Tables keep 12 pt data/10 pt headers and single
spacing, with no extra paragraph-after gaps and 1 pt vertical padding. Numbered
full-width notes reserve enough label space inside the table border.

Recognized existing framed sections reserve top/bottom body margins of at least
16/35 mm without moving the frame artwork. Contents with the larger first stamp
receive a separate 57 mm bottom work area. The proven full-page change-register
form gets its own section with original margins, avoiding a nearly empty extra
page of blank grid rows. Empty trailing sections are not treated as main prose.
These settings support the reviewed existing form; they are not universal GOST
page margins or full conformity certification. Updated README, formatting guide
and AGENTS.md to state this scope and the retained 1.5 spacing requirement.

Validation: **195 tests passed, 4 optional runtime tests skipped by default**;
all three live document-runtime tests passed separately, including two long
tables whose positions affect each other. Strict mypy passed for all 30 checked
modules, desktop/worker syntax checks and diff whitespace checks passed. Doctor
reported ready; deterministic retrieval evaluation passed (source recall@1=1.0).
The final rebuilt image processed the retained byte-identical original DOC into
24 editable pages with zero unresolved TOC targets. The exact final DOCX was
rendered with the bundled renderer and all 24 pages visually reviewed; the final
note-indent adjustment changed only pages 9, 11 and 22 by pixel comparison.
Continuation captions appear on pages 8–11, the equipment table fits one page,
the change-register grid fits one page, and the formerly sparse section-ending
page now includes the following section. Checked 141 main prose paragraphs for
line=360 (1.5); the greatest inspected main-body ink bottom was 741.07 pt, above
the stamp. Compared 37 technical/appendix table data rows against the retained
baseline, including cell values and merge signatures. All nine original media/OLE
payload hashes remain present, plus the already disclosed derived display copy.
The original DOC hash is unchanged. Private source, final DOCX, renders and audit
JSON remain ignored under eval-results and are excluded from Git.

## 2026-11-13 — Actual agent file delivery and detailed answers in both routes

The file panel was not hiding saved sorting files: the affected conversation
contained prose/code promises and no verified write. LocalAgent previously
accepted a tool-free final response whenever no mutation had been attempted,
so the receipt guard never ran in precisely this case. Added a current-request
delivery guard with at most two tool-call repair messages. It never writes code
parsed from Markdown or bypasses approval. Missing tools/receipts produce an
explicit unsaved outcome; refusal/cancellation do not trigger another write.
Questions, prohibitions, quoted examples and appended attachment-copy metadata
do not enable the guard. Existing mutations still report only verified receipts.
Recent model history is bounded to 3000 characters, preserving complete newest
turns where possible and marking a single oversized excerpt; stored history is
unchanged. The live selected model supported tools but had an allocated 4096-token
context. This is a context-pressure risk, not proof of the cause of every missed
tool call; neither Ollama's global settings nor the installed model were changed.

Document questions with the agent switch on now prefetch through the same scoped
retrieval service and use the same detailed answer policy as SEARCH. Search tool
results enable the policy for later agent steps too. Added the independently
configurable DOCUMENT_ANSWER_MAX_TOKENS=4096 budget. Fixed the Ollama adapter so an
explicit max_tokens override is not overwritten by the default completion limit;
this also restores the router's intended small budget. Current-turn brevity is
honored without inheriting older short-answer examples. Broad short explanations
with substantial evidence get one bounded expansion; substantive answers may
instead get one compact source/draft review without write tools. Review is by the
same selected local model, is not an independent fact check, may still leave
unsupported claims, and can add a generation pass of latency. Review failures
retain a completed draft, and cancellation still stops the request. Source
labels and the application identity are retained. README and AGENTS document
these boundaries; all calls remain local through the existing Ollama endpoint.

Validation: 229 tests passed, four optional runtime tests skipped. Strict mypy
passed for all 32 checked modules; desktop syntax checks and git diff whitespace
checks passed. Doctor reported ready with both stores healthy; deterministic RAG
evaluation passed (source recall@1=1.0). Regression tests force the old prose-only
failure, verify three saved files/three approvals, repeated-prose failure,
rejection/cancellation, route parity, brief requests, token-budget precedence,
bounded history, source review and the one-pass limit. An integrated Flet callback
test verifies the approval modal and actual rows in the current chat's file panel.
The vision observation test now requests an explanation instead of expecting a
fictional saved result with no write tools.

Real qwen2.5:14b verification used a read-only copy of the affected conversation
context and a separate QA workspace: bubble/quick/merge sort files were created,
each approved once, each passed syntax parsing, and their receipts matched the
file panel's listing function. No user chat messages or original documents were
rewritten and generated Python was not executed on the host. A real retrieval
query fetched the existing local documentation once; both response routes were
then compared against that same cached evidence. The final SEARCH/AGENT answers
contained 284/248 words and retained both source labels, versus the earlier short
paragraph. These lengths demonstrate fuller explanations, not guaranteed factual
accuracy; manual comparison remains necessary. Private histories, documentation,
model answers and QA files remain ignored under eval-results and out of Git.

### 2026-11-13 — Restore the chat sidebar at startup

ChatManager already restored the saved conversations and selected the newest;
the desktop constructor omitted the initial sidebar refresh. Populate it as soon
as the controls are mounted, without creating a chat or changing stored history.
Validation: 17 startup, chat-store and activity/UI tests passed. The regression
test reopens a temporary SQLite database with two conversations and checks both
sidebar entries and the latest messages before any user action.

### 2026-11-14 — Project folders, bounded code context and project tests

- Added desktop «Открыть проект»: a request-owned cancellable worker imports the
  selected folder into an immutable per-chat snapshot with preserved paths and
  verified hashes. Fixed filters exclude known dependencies/caches, hidden files,
  common secret names, symlinks, non-UTF-8 and binary files. This is not a full
  .gitignore implementation or secret-content scanner. Limits: 1500 files,
  1 MB per input file, 16 MB total; excess rejects the whole import. Reimporting
  makes a new ID. No source files are overwritten or added to Chroma.
- Added scoped project listing, paged Python AST map (functions/classes/imports),
  and literal whole-project search returning paths/line numbers. Other text
  languages support file navigation/search but not AST symbol maps/test runners.
- The first approved project edit validates every source hash and atomically
  publishes a complete results/projects copy containing unchanged dependencies
  and the approved modification. Later reads/search/edits follow that working
  tree even through old input paths. No partial result on refusal/cancellation.
  File approval includes a bounded unified diff and exact full future content;
  writes still return verified FileReceipt artifacts. Files panel pages 50 rows.
- Agent context removes whole old tool exchanges with a bounded navigation ledger,
  preserving original task/instructions and tool-call pairing. Tool excerpts are
  explicitly marked when shortened. The character budget (16000 default) is an
  approximation excluding tool schemas, not an Ollama token-window configuration;
  an unfit request stops truthfully. Step limit defaults to 30. Stored history is
  untouched. No model/server global settings or providers changed.
- Existing isolated Docker runner now executes an imported project's latest
  filtered snapshot with its project root as CWD; pytest accepts a test file or
  directory. No host-code fallback, package installation, network access or new
  container privileges. Existing time/output/resource limits remain in effect.

Validation: startup, intake, filtering (including FIFO/symlink rejection), limits,
cancellation, stale picker results, chat scope, snapshot tampering, exact diff
approval/receipts, file-panel pagination, context pairing and tool-driven test
repair have regression coverage. Strict mypy passed all 34 hardened modules;
desktop integration compiles. Doctor reports ready=true and both SQLite stores
pass integrity checks. Deterministic retrieval evaluation remains unchanged.

Live verification with the already prepared butuz-sandbox:local image passed the
project-root regression (initial failing test, approved addition fix, passing test)
and existing container/network/write boundaries. Real qwen2.5:14b independently
completed the same synthetic four-file project task through SmartRAG in about
64 seconds: actual pytest AssertionError/exit 1, one approval, verified edit,
actual 1 passed/exit 0. The original folder remained byte-identical. This was a
small reproducible task, not a large-repository reliability benchmark. Evidence
is ignored under eval-results/project-folder-fix; only synthetic tests/code are
staged. Flet picker/modal/file-list callbacks were tested with real controls and
a running page loop; a native desktop window was not manually exercised here.
Final offline suite: 246 passed, 5 optional runtime checks skipped; the selected
project and container boundary checks also passed with the prepared image enabled.

### 2026-11-14 — Fix project selection and complete the native desktop check

The real desktop check exposed a gap the original mocked-picker test missed:
the native FilePicker did not visibly open/return a selection, while the pending
chat flag made subsequent «Открыть проект» clicks no-ops. Replace that path with
a visible in-app ProjectFolderBrowser. It opens before filesystem work, lists
bounded directory pages off the page loop, supports direct absolute paths and
folder navigation, and keeps invalid paths editable. Empty/relative paths cannot
implicitly choose the application's own directory. Cancel, dismiss, chat switch
and shutdown release session ownership; old listing/confirmation callbacks cannot
import into a different chat. No persistent runtime data or original files moved.

Validation: 251 tests passed, 5 optional runtime tests skipped; strict mypy passed
all 35 hardened modules, and desktop integration compiles. Tests exercise actual
Flet modal actions on a running loop, invalid-path retry, cancel/reopen, late
dismissal, stale chat confirmation and the end-to-end import callback instead of
mocking get_directory_path as proof of a visible chooser. Doctor reports ready
with intact chat/Chroma SQLite stores; deterministic retrieval recall@1 remains 1.

Native GUI verification (uv-launched app, qwen2.5:14b, existing local Docker):

- On startup, existing conversations and the latest conversation appeared before
  using «Новый чат». A separate diagnostic chat was then created through the GUI.
- «Открыть проект» displayed the new modal, cancellation allowed reopening, and
  folder navigation imported the synthetic four-file gui_math_demo tree with zero
  exclusions. Agent mode and the project label appeared in the real window.
- The agent actually ran pytest in the sandbox and showed AssertionError / exit 1.
  Its approval modal displayed the exact result path and `a - b` → `a + b` diff.
  Approving it published the complete working project and a verified file receipt.
- The first request stopped without rerunning tests and retained an earlier wrong
  relative-path error in its report. An explicit GUI follow-up targeting the
  results project's tests produced actual `1 passed in 0.00s`, exit 0. This is a
  documented model-workflow limitation, not evidence of a guaranteed autonomous
  repair loop or large-project reliability.
- The real «Файлы чата» modal listed all four result files, including package/calc.py,
  with reveal/export actions. Readback verified the corrected bytes; hashes of all
  four host originals and all four input-snapshot files still matched the baseline.

The app remains open on the diagnostic chat's file panel for inspection. Private
GUI evidence and synthetic workspaces are ignored under eval-results/agent_workspace
and are not committed. No cloud requests, model downloads, host execution of
generated code or bypass of write approval were used.

### 2026-11-15 — Verify the latest edit without another user reminder

The GUI investigation showed that a verified FileReceipt was enough to end a
fix-and-check request even when its only pytest result preceded the write. Add
request-owned PostEditVerification outside the compacted model history. It
recognizes current explicit code-edit plus runtime-verification requests, excludes
quoted examples, prohibitions, filename words and syntax-only tasks, and leaves
general document/file workflows unchanged.

Every relevant successful write invalidates earlier verification. ExecutionResult
now carries trusted pytest/python kind, actual copied-project root, selected test
target and input SHA-256 fingerprints. Only pytest artifacts matching current
written bytes and project scope count. Separate earlier test files must all be
repeated, or covered by a containing suite; another project or a smaller/different
suite cannot satisfy completion. Runtime reports identify their target; fix-and-
check outcomes distinguish pre-edit and post-edit runs.

When the model tries to finish too early, the host may repeat only the same
model-selected, actually executed test target through the existing request-owned
run_pytest tool. This validation step is explicitly tagged in AI message metadata
and uses the same cancellation/isolation path; it cannot choose new commands,
run shell/host code, install packages or skip GUI write approval. Unknown targets
use bounded model repair. A request has at most two such completion repairs;
step/context budgets, cancellation and rejected writes still stop work. Missing
runtime/tools, invalid paths, exhausted attempts and failing/unfinished tests
produce explicit warnings with actual results, never a claim of passing tests.

Validation: 299 offline tests passed, 7 optional checks skipped; strict mypy passed
all 36 hardened modules and desktop integration compiles. Regression coverage
includes the original pretest/write/prose sequence, multiple edits in one tool
batch, several projects/suites, mismatched hashes, bare/unrelated execution
artifacts, syntax checks, missing Docker/tools, cancellation, refusal and limits.
The prepared local Docker passed four boundary/project checks, including a real
failed test, approved correction, premature model prose and automatic successful
rerun without a second model tool decision. Targeted live checks were repeated
after the final suite-coverage change. Doctor is ready with intact stores;
deterministic retrieval recall@1 remains 1.

Real qwen2.5:14b was checked using synthetic isolated QA projects. A broad request
still exposed a model path-selection mistake: it edited a different calc.py,
repeated tests stayed red and the final report correctly showed failure. This is
not repaired by a completion guard and remains a code-quality limitation. With
explicit file/suite paths, one request completed in about 31 seconds with one
approval, the correct addition fix, an unchanged test file, 1 failed before the
write and 1 passed after it. Host originals stayed unchanged. The latest change
was tested through the worker/tool API and real Docker, not a fresh native GUI
session; restart the existing desktop process to load it. Private QA artifacts
remain ignored under eval-results/post-edit-tests and are excluded from Git.

### 2026-11-15 — Unassisted multi-file project benchmark

One fresh request to local qwen2.5:14b used a synthetic nine-file, 135-line Python
sales-report project with two related production bugs and 12 existing tests.
The task specified discount/paid-revenue behavior, unchanged public API/tests/tree,
before/after pytest and delivery to Chat Files, without exact bug locations.
Six independent acceptance cases were withheld from the agent. The request took
about 36 seconds; no corrective follow-up or manual candidate repair was used.

Outcome: failed. The model selected an absent sales_report.py and invalid pytest
paths, then proposed creating a new file rather than changing the existing
production modules. The QA reviewer rejected that out-of-scope creation under the
unchanged-structure condition. Rejection ended the request, so this run does not
establish what would happen if that incorrect write were approved. There were no
verified writes or output project. The app truthfully reported unsaved output
and unconfirmed test calls instead of claiming success.

Independent real-Docker checks of the unchanged candidate still show 7 failed /
5 passed in the public suite and 6 failed in holdout cases. A separate reference
with only the two known production fixes passes all 18 cases, validating the
fixture. Original-folder and imported-snapshot SHA-256 values remain unchanged;
existing tests are intact. Candidate code never ran on the host.

This was a worker/API check with real Ollama and Docker, not a completed native
GUI flow: the app opened but computer-use clicks were unavailable. A trusted QA
script imported only the newly authored synthetic fixture and reviewed writes.
The diagnostic request/answer are saved in a separate local chat. Private reports,
fixtures and working copies remain ignored under eval-results/project-benchmark
and agent_workspace. Project support exists, but autonomous path selection and
dependent tool sequencing remain a demonstrated quality limitation, even on
this small example; this is not evidence of large-repository reliability.
Read-only doctor remains ready with intact stores; deterministic retrieval
recall@1 is 1. No application code changed in this benchmark stage.

### 2026-11-15 — Make project tool decisions depend on actual results

The failed benchmark exposed a model-generated batch containing navigation,
reads, writes and tests whose arguments had all been chosen before any results.
For requests with imported projects, disable parallel calls and run only the
first model-selected tool per decision. Every remaining call gets an explicit
not-executed ToolMessage, preserving complete tool pairs for context compaction.
The model must choose again after receiving the real result; deferred writes are
never silently queued or approved. Trusted automatic post-edit suite repeats are
independent and retain their existing scope and cancellation rules.

ProjectFlow is request-owned and seeded from trusted chat tool metadata, not
project text. ProjectRead artifacts bind actual displayed ranges to SHA-256.
Existing-file edits require current-version read coverage; whole replacement or
append requires full coverage, possibly through adjacent pages. Truncated lines
do not count. Write receipts invalidate reads for both input/result aliases.
Errors do not repair guessed paths by basename or change tool arguments. New
files and general document/chat tasks still use normal permissions and approval.
Narrow explicit current-user constraints can preserve conventional test paths
and require a real same-project pytest artifact before changes; quoted examples
and negated requirements cannot enable these restrictions. Project decisions use
temperature 0; remove the conflicting instruction to write before studying input.

Intermediate fresh unassisted runs remained incomplete: sequencing alone reached
real files but proposed appending a test despite the unchanged-tests condition
(rejected at review). With request constraints, it ran an actual baseline test but
struggled with paths/escaped Python and reached the 300-second QA timeout without
a write. Ollama ps then revealed the selected model actually had only 4096 tokens
of context, despite the separate 16000-character application message budget and
additional tool schemas. This is a plausible contributor, not proof of a sole
cause. The existing /v1 interface cannot set num_ctx per call.

Prepare an explicit separate butuz-qwen2.5:14b profile from already-installed
qwen2.5:14b weights using ollama/Modelfile.agent, without downloads or changing the
original model. Actual Ollama ps confirms 16384 context and approximately 11 GB
memory. Runtime never prepares it or changes model selection automatically;
README and .env.example explain setup and selection. A first 300-second run with
this profile published pricing.py and actually ran its tests after the write,
but timed out before completing the task. Independent Docker evaluation found
9/12 public and 1/6 holdout cases passing: do not count this as success.

Regression validation: 312 offline tests passed, 7 optional tests skipped; strict
mypy passes all 37 hardened modules. Two prepared-Docker project/post-edit checks
also pass. Doctor reports intact stores and local readiness; deterministic RAG
recall@1 remains 1. Private per-run audit logs, fixtures and chat workspaces stay
ignored. A fresh temperature-0/16k trial with the unchanged task and fixture used
the application's complete 30-step limit (563 seconds), without the earlier
five-minute cutoff. It ran all 12 baseline tests at the real project root, then
repeated invalid edits containing escaped separators and copied line-number
labels. Syntax checks prevented publication; all 7 public failures and all 6
holdout failures remained. Clarify the raw-source contract in replace_lines and
the agent prompt: displayed line numbers are metadata, not replacement source;
single-line fixes should supply only that line. Do not silently strip labels or
invent a corrected candidate. Repeat the original task on a fresh copy once more
with this final tool contract, the same 16k weights and 600-second QA deadline.

Final source-contract trial: one unchanged request on a fresh nine-file fixture,
no follow-up hints and no manual candidate repair. It completed at the normal
30-step limit after 552 seconds, rather than the QA deadline. Actual tools read
README and source, ran baseline pytest, published one reviewed pricing.py copy,
and ran pytest against the latest project. The final result truthfully reported
failed post-edit verification and the exhausted step budget. Independent Docker
checks found 7/12 public and 4/6 withheld tests passing, compared with 5/12 public
before changes. The implementation reduced discounts but removed discount-range
validation and retained unreachable old code; reporting.py remained unchanged.
Repeated escaped/number-prefixed edits of that second module never passed syntax
validation or opened approval. This is still a failed overall project task, not
a reliable autonomous repair result or evidence for large-project readiness.

SHA-256 readback confirms all host originals, input-snapshot files and tests are
unchanged. The complete partial output tree is visible in that diagnostic chat's
Chat Files; its receipt verifies the one actual mutation. Local evidence is in
eval-results/project-benchmark-source-contract. Intermediate runs are retained
and labelled separately; they are development observations, not a statistical
success-rate evaluation. All used the worker API, local Ollama and real Docker,
not a newly validated GUI session. A final receipt-format adjustment returns
the short canonical workspace-relative path instead of a long host/hash path;
its absolute receipt and GUI approval path remain intact. This adjustment has a
dedicated regression and the full 312-test run; the long live trial preceded it.

The original .env model selection was preserved. The optional 16k local profile
is installed for explicit selection; restarting the desktop process is needed
to load the new agent code. Doctor still reports ready/intact stores. Remaining
limitations are model code correctness, repetitive malformed tool arguments and
task completion despite receiving actual errors; path/read guards cannot turn
these into successful repairs, and the report does not claim they do.


## 2026-11-16 — exact project repair decisions and test feedback

Add replace_text: one unique literal source match, current read coverage, Python
syntax validation, full exact GUI approval, atomic project-copy publication and
verified FileReceipt. Preserve unrelated bytes, including CRLF. The repair-mode
schema requires a single-line/expression old_text anchor, avoiding indentation
reconstruction for a multi-line old block; universal file tools keep their
normal multi-line contract. No fuzzy edits, source-label stripping, Markdown
execution or weakened escape decoding.

For explicit code repair plus runtime verification on imported projects, use a
small tool surface and request-owned ProjectRepair state. Each decision keeps
the complete current request, actual navigation/read evidence with current
hashes, recent actual actions and the last complete tool exchange. Old rejected
assistant proposals are not replayed. Reply to all deferred call IDs, placing
the actual executed result last. Discover project IDs once. After source-format
errors require a fresh typed read; at most three metadata-labelled automatic
refreshes can repeat exactly a successful model-selected read. Never choose a
new file or patch in host recovery logic.

Keep hash-current verified saved Python source as WRITE-result evidence outside
context compaction. It does not grant permission for another edit; ProjectFlow
still invalidates the prior read on a receipt. Preserve real full test artifacts;
shorten model feedback with the failure summary, not only its beginning. Require
a current actual project-root pytest for whole-project requests; narrow explicit
scopes remain narrow. Reject chat-root pytest rather than collecting input and
output copies. In a single-project repair, hide/reject repeated execution of an
already failed unchanged root version until a saved edit. Do not apply this to
multi-project or explicitly narrow requests.

Use native Ollama tool_choice=required while read recovery, failed tests or a
missing/stale requested scope remains. Return to auto after actual evidence
permits completion. A local /v1 smoke call confirmed required tool selection is
supported. Before the next dependent action after writing, the existing trusted
post-edit validator may repeat ONLY model-selected, actually executed targets;
reply that the original model call was not executed or queued. Broader/new test
targets remain model decisions. Preserve ordinary rejection/cancellation/bounds.
Tool-free failure analysis by the same selected model is optional, bounded and
triggered after a premature finish. Its hypotheses are not correctness proof.

Development trials are retained separately under ignored project-repair-v1
through v21 directories. They are iterative observations, not a success-rate
study. V8 repaired a fresh nine-file/135-line fixture with two correct small
edits: 12 public and six withheld cases passed in independent real Docker.
Subsequent repeats still exposed malformed old blocks, speculative rounding,
repeated unchanged tests and premature prose-only endings. A trial of mandatory
model patch criticism incorrectly rejected a valid paid-status fix in v17;
remove that veto. Same-model opinion cannot replace approvals or actual tests.

V18 with native required tools passed all 12 original public cases and the six
original withheld cases, but manual review found an invented completed status.
A seventh independent acceptance case exposed that defect. V19 uses the SAME
request and production source, with an added ordinary project test that all
non-paid external statuses are excluded; no line/file fix hints or manual
candidate edits. The strengthened fixture has 13 public cases. The 30-step v19
trial remained incomplete: 9/13 public and 4/7 independent cases passed. Set the
explicit default AGENT_MAX_STEPS to 60 (existing environment overrides still win,
range remains 5–60). Do not conflate this with the earlier 12-case fixture.

V20, using the larger bounded budget, made both correct production edits;
13 public and seven independent acceptance cases passed. However, the agent
selected only the tests directory and the whole-project completion guard still
reported the missing root check. Supply the canonical root from actual receipts
or execution metadata in the pending-scope ledger, rather than only a project
ID. This is navigation evidence, not a host-selected test command. Permit up to
six premature-finish repairs, still within the overall step budget.

V21 is a fresh import of the same strengthened fixture with the SAME request,
no follow-up hints or manual candidate edits, and the final implementation.
In 316 seconds, the agent read the project, selected and ran root pytest before
editing (eight failures/five passes), made two approved literal changes, and
ran root pytest after the latest change: 13 passed. The existing request-owned
validator also repeated an already model-selected root scope. Independent real
Docker validation passed all 13 public and seven withheld acceptance cases.
Only pricing.py's discount sign and reporting.py's paid-only condition changed;
validation, Decimal/HALF_UP rounding, API and other source remain intact. The
original folder, imported snapshot and existing tests have identical SHA-256
hashes to their pre-import versions. The complete nine-file output is present
under that chat's results/projects path. Evidence: ignored
eval-results/project-repair-v21/{run-metadata,model-report,tool-audit,summary}.json
and public/holdout-pytest.txt; the local Russian report links the output folder.
These successful small-fixture checks do not erase the failed intermediate
trials or establish a general model success rate.

Live checks use the pre-existing butuz-qwen2.5:14b profile with 16384-token context
and the same local Qwen weights, plus the prepared offline Docker sandbox. No
model/dependency/image downloads; no candidate code execution on the host. QA
approval callbacks allow only the synthetic production modules. Host originals,
input snapshots and existing tests are hash checked. Worker/API tests do not
establish a new native GUI pass. The original .env selection stays unchanged;
the normal 4k Ollama model context is not the validated 16k profile, which the
user selects explicitly. Small-fixture results do not prove reliable repair of
arbitrary large projects.

Implementation checks: 347 offline tests pass, eight optional tests skipped;
strict mypy passes all 38 hardened modules. Four prepared-Docker execution,
project-root/latest-copy and automatic-post-edit tests pass. Syntax compilation,
read-only doctor (ready/intact SQLite and Chroma), and deterministic RAG recall@1
(1.0) pass. PyPDF2 emits its existing deprecation warning. Runtime QA data,
chat histories, fixture copies and test output stay excluded from Git.

## 2026-11-17 — complete source archive and explicit standards coverage gaps

First delivery stage for the expanded standards library, with technical
specifications (TU) explicitly chosen by the user as the first document kind.
This is NOT completed semantic extraction or implementation of every rule.

Register seven exact supplied editions in standards/library.json: the existing
R 2.105-2019 and R 2.104-2023 (matching their previous SHA-256), plus 2.702-2011,
R 2.610-2019, R 2.106-2019, R 2.102-2023 and 2.413-72. The five new PDFs have
138 pages; the whole library has 203. Keep full original PDF copies (visuals
included), all extracted page text and 1375 lossless page-local navigation
fragments in ignored data/standards_library/v1/. Every fragment remains an
unreviewed candidate, not necessarily an atomic requirement. Images/geometry,
tables, applicability, exceptions and cross-page continuations need review.
Do not claim that all rules have been semantically captured or checked.

standards_library imports explicitly registered hashes/page counts only, verifies
the registered extracted-text fingerprint, atomically publishes complete copies
and rejects corrupt, modified, incomplete or symlinked editions. Existing
editions and host originals are not overwritten. Search is literal, bounded and
scoped to one edition, with page/hash citations and explicit partial excerpts.
Separate top-level headings from earlier contents entries when proposing clause
navigation; numbers are still unverified candidates. Unknown standards/versions
are not guessed. PDF and derived text stay local, with no downloads/OCR or new
Chroma database/collection. No new dependencies were installed.

Universal AGENT tools list_standards/search_standard/read_standard_page use
request-owned cancellation and source lists. Code-project repair tools remain
restricted to their earlier smaller surface. Ordinary SEARCH still uses the
existing shared document retrieval service; automatic corpus routing into that
route is not implemented by this stage. These are source-reading tools, not a
general normative execution engine.

Add standards_coverage: include every archived navigation candidate, all seven
sources, the 33 earlier rule records and the 14 selected recipe records. Bind
each report to exact candidate DOCX bytes. An implemented transformation or
retrieved excerpt cannot confer a passing/fulfilled status. Keep applicability
unresolved and unimplemented checks explicit; report zero automatic normative
pass conclusions, no compliance percentage and no certificate. TU reports mark
the missing full ГОСТ 2.114 source; operating-document and electrical-diagram
standards are not automatically applied to technical specifications.

The desktop now captures document kind in a native in-app modal before running
the job, rejects stale chat/attachment selections, and adds a Coverage tab to
the exact-byte approval dialog. Publication retains existing approval,
cancellation, preservation and FileReceipt requirements. The current formatting
recipe/container transformations have not changed and need no image rebuild.
Coverage is host-side read-only analysis; it does not introduce host conversion.
CLI can export a complete JSON coverage inventory to a new report path only.

Validation: 359 offline application tests pass, eight optional tests skipped;
strict mypy passes 41 hardened modules. A separate prepared-Docker document
export passes and its returned DOCX hash binds the coverage report. Actual native
modal/approval callbacks are exercised, including exact candidate text, missing
TU dependency, stale ownership and rejection. Read-only doctor reports ready,
SQLite/Chroma intact; deterministic RAG recall@1 remains 1.0. The existing PyPDF2
deprecation warning remains. The new desktop process opens visibly, but Computer
Use clicks still fail with noWindowsAvailable even after Raise: this does NOT
constitute a successful native GUI interaction pass. Local evidence includes
eval-results/standards-intake-2026-11-17/coverage-final.json and gui.log.

Remaining work: verified semantic rule records/conditions/dependencies for the
new editions, additional explicit profiles and independent per-rule validators,
visual-example interpretation and real GUI approval verification. For TU,
obtain the full ГОСТ 2.114 source before claiming content coverage. Full-source
retention and an honest gap inventory are a foundation, not complete compliance.
Keep supplied PDFs, corpus text, private document examples and runtime evidence
out of Git. Preserve the unrelated hybrid_retriever.py user change.

## 2026-11-17 — five further sources, TU source-state correction

Register and explicitly import the additional supplied PDFs: ГОСТ 2.414-75
(December 2010 edition with amendment 1), 2.701-2008 (supplied 2009 publication),
2.710-81 (supplied copy including amended text), 2.601-2013 (August 2018 reprint)
and 2.114-2016 (December 2018 reprint, 2019 cover). Read identity/scope text and
visually inspect the first page of each supplied PDF. These observations do not
establish current legal status or a complete visual/semantic review.

The five new sources have 81 pages and 748 navigation candidates. The preserved
library now contains 12 exact editions, 284 pages and 2123 page-local candidates.
Verify all stored PDF hashes, registered extracted-text fingerprints and complete
concatenation of candidate spans to every extracted page. Keep images in the
unchanged PDF; no drawings are regenerated. Earlier entries/editions are retained.
Only metadata enters Git, not PDF/text copies or private QA artifacts.

Remove the hardcoded TU-source-absent warning. Coverage now distinguishes an
unavailable/unverified local copy from a verified stored ГОСТ 2.114-2016 whose
content checks remain unimplemented. Corruption still stops reporting rather
than silently becoming absence. Both states retain incomplete conformity and
unchanged rule outcomes; intake does not enable new transformations or passing
checks. The preflight GUI uses neutral wording and the report supplies actual
availability. Existing formatting selections and container fingerprint remain
unchanged; no image rebuild is required.

Preserve ГОСТ 2.601-2013 as a separate source. The supplied Р 2.610-2019 cites
Р 2.601-2019 as well (including its page 1 note and page 3 definition reference).
Record an edition-substitution review notice in source metadata and coverage;
do not treat the provided 2013 text as the 2019 edition. This is supplied-text
evidence, not a determination of either standard's present legal applicability.

Validation: 362 application tests passed, eight optional tests skipped; strict
mypy passes 41 hardened modules. Added synthetic regressions for absent/present/
corrupt TU sources, unchanged verification outcomes after intake, the operating-
document edition notice and pagination beyond the first ten catalog entries.
Doctor reports local readiness and intact SQLite/Chroma. Deterministic RAG
recall@1 remains 1.0; the existing PyPDF2 deprecation warning remains. No model,
dependency or image downloads, no new database/collection and no new automatic
normative check. This stage does not establish a new native GUI interaction pass.
Local audit: eval-results/standards-intake-2026-11-17-b/{summary,coverage}.json.

## 2026-11-17 — formatted TU artifact and scoped document checks

Prepare a fresh editable DOCX from the existing private legacy TU using only the
prepared offline document container. Retain the original DOC SHA-256 unchanged.
The result has 24 rendered pages: existing title/frame/stamp geometry, technical
text and values, tables and original opaque diagram/OLE parts are preserved.
The existing recipe retains 1.5 prose spacing, calculated table parts, four
continuation captions and refreshed TOC caches with zero unresolved targets.
The disclosed legacy diagram display copy uses Liberation Sans for the missing
GOST font; originals remain intact. No missing technical prose is invented.

Inspect all 24 page PNGs and independently read final PDF captions. An initial
visual suspicion of omitted captions was disproved by single-page PNG inspection
and PDF positions: the captions are present. Do not claim a table-layout bug was
fixed in this stage; that algorithm and the container image are unchanged.
After final preparation, every page PNG is byte-identical to the reviewed page.
CLI publication (the workspace-only exception, not a bypass of GUI approval)
adds a new uniquely named DOCX and review Markdown in the original document
chat's results folder. Exact readback produces FileReceipts; output_files confirms
visibility. Previous outputs/originals and stored chat messages are not replaced.
The final document is formatted for author review, not a compliance certificate.

Add tu_validation read-only measurements gated in coverage by explicit TU kind,
availability and the pinned provided ГОСТ 2.114-2016 SHA-256. Measure A4 section
sizes and explicit 1.5/zero-gap properties of recognized main prose; unknown
section dimensions cannot become a positive result. Proven adjacent table
captions are excluded from prose spacing. For this document, all five section
sizes measure A4 and all 141 recognized prose paragraphs match that spacing.
Observe introductory wording and real Heading 1 section headings, without
counting contents or Heading 3/4 requirements as main sections. Missing separate
safety/environment/operation/warranty headings require TZ/developer confirmation
under 5.1.2; they are not automatically violations and no empty sections are added.
The source refers to separate common TU. That referenced document and the basis
for developer-selected composition are unavailable, so full content validation
remains unresolved. Report actual observations separately from the 33 existing
normative records, whose overall conformity remains unassessed.

Retain bounded PDF preview bytes on DocumentCandidate. Before returning a prepared
document, the host checks explicit continuation captions adjacent to tables in
the final rendered PDF, on distinct pages within page bounds; missing/clipped
captions prevent publication. Ordinary text mentions without a table are ignored.
The private artifact passes all four caption checks. This test does not prove
row fit, drawing correctness or complete GOST compliance. No host conversion,
model-generated code, downloads, new collections or changed formatting recipe.

Validation: 372 application tests pass, eight optional tests skipped; strict
mypy passes the 42 hardened modules (and the final TU module separately after
the last guard refinement). A prepared-container export passes; the private
24-page document was also rendered through the actual container and checked.
Read-only doctor reports ready/intact SQLite and Chroma; deterministic retrieval
recall@1 is 1.0. The existing PyPDF2 deprecation warning remains. New synthetic
tests cover scoped measurements, developer exceptions, TOC/Heading 3 exclusion,
unknown page sizes, lost/duplicate-page/clipped captions and non-caption prose.
No new native GUI interaction pass is claimed. Private evidence and the
publication receipts remain under eval-results/tu-gost-ready-2026-11-17/;
the technical source, candidate, pages, PDF and report stay outside Git.

### 2026-11-17 — Enumeration wrapping and scoped list review

Fix the supplied TU's paragraph-style enumeration wraps while retaining main
prose spacing 1.5. `list_layout` resolves direct and inherited numbering, level
overrides and body outline level 9; a false bidi property does not imply RTL.
Recognized list/numbered-note first lines have a positive indent and continuation
lines return to the text boundary of their level. The 12.5 mm step and 6.35 mm
label slot are explicit project choices under the provided edition's 6.7.2/6.7.8,
not dimensions inferred from the illustration. Numbered notes are separated from
enumerations. Section/requirement headings, tables, fields, actual RTL and unknown
constructs remain protected. A shared counter with any unclassified user cannot
be restyled. Tabulated list text remains for manual review rather than losing its
column-like alignment. Only whitespace-adjacent plain run breaks can be removed;
text nodes, page/column/clear breaks and ambiguous breaks are preserved.

Rendering demonstrated that numbering-level hanging geometry can override the
paragraph properties. Add isolated abstract-layout copies for fully classified
counter users, retaining original definitions, paragraph counter IDs/levels,
numbering formats, restarts and font runs. Never renumber body requirements or
replace document text. Audit nested punctuation endings, introductory colons,
capitalization, marker choice and repeated numbered counters; expose review
warnings without changing technical names, abbreviations or punctuation.
Add the reviewed layout evidence record and explicitly select layout/punctuation
in the two-source recipe (34 catalog records, 16 selected). Include the new helper
in Docker's allowlist, fixed COPY and host/image freshness fingerprint.

Update the prepared local document image without downloads: the original build's
system-package layer was not cached, so its network-disabled build failed. The
successful explicit setup copies only reviewed fixed code/evidence over the
previously prepared image ID a7efc27973c131d5ccf11ca18abe02e3650c9cc9b5ffcf28fc1effe6748c0974.
No host converter or package-download fallback was used.

Prepare and publish a new workspace-only CLI copy and review report under the
same document chat, with exact FileReceipts and output_files visibility checks.
The original DOC hash is unchanged. The 24-page result adjusts 10 enumeration
items and six numbered notes and removes one proven obsolete manual line break.
All text nodes, paragraph counter IDs/levels, original numbering definitions and
10 opaque media/OLE parts match the previous delivery. Four continuation captions
pass final-PDF checks. Inspect changed pages 3, 14–21 and 23; other pages match
the previously reviewed output. Every final PNG matches the reviewed candidate.
Three punctuation endings and two lists' initial uppercase wording are flagged;
the seven-item tabulated indicator list remains explicitly for manual review.
Existing missing-font display-copy disclosure and incomplete-conformity warnings
remain visible. Do not claim full GOST verification or native Microsoft Word QA.

Validation: 385 application tests pass, nine optional tests skipped, with the
existing PyPDF2 deprecation warning. Two additional prepared-container checks
pass: complete export plus rendered coordinates for all four nested levels
(letter/Arabic/Roman/hyphen) including actual continuation-line and first-line
positions. Strict mypy passes all 43 hardened modules. Read-only doctor is ready
with intact SQLite/Chroma and local Ollama (the initial restricted-network check
could not connect; the enabled loopback check succeeds). Deterministic retrieval
recall@1 remains 1.0. Private candidates, previews, reports and publication
receipts stay in ignored eval-results/list-layout-2026-11-17/ and chat results;
no new GUI interaction pass is claimed. Preserve the unrelated user edit in
hybrid_retriever.py outside this commit.

### 2026-11-17 — Keep quantities and units on the same line

Review the supplied ГОСТ Р 2.105-2019 PDF page 30: clause 6.16.6 prohibits
separating a value and its unit across lines/pages (with the printed-typewriter
table exception). Add the reviewed unit-nonbreaking evidence record and select
it explicitly: 35 registry records, 17 selected in the two-source recipe.
`unit_spacing` replaces only existing ASCII spaces with NBSP at validated
node/character offsets, including across styled runs, known compound units,
grouped digits and supported parenthesized tolerances. Retain every digit,
unit character, punctuation mark, run property and field instruction. Keep the
existing exact-text preservation guard before this narrowly permitted final
whitespace step; never globally decode/normalize or rewrite technical prose.
Recognized Russian year abbreviations and ambiguous seconds/preposition cases
are excluded. Fields, links, revisions and drawing text stay opaque; tabs,
manual breaks and paragraph boundaries are not silently joined. The finite
unit vocabulary and unresolved notation are not a complete SI interpreter.

Add the module to the fixed Docker COPY/allowlist and runtime fingerprint.
Update the prepared image offline over the same existing local base; no new
packages, host converters, models or network downloads. The existing GUI
approval previews receive the resulting exact candidate text and hash.

Prepare another fresh TU from the original DOC in that isolated runtime:
72 quantities bound, 99 spaces replaced, 24 pages. Independent comparison to
the previous delivery after applying the exact same bounded rule confirms all
remaining text/field instructions and the complete numbering part unchanged;
10 opaque media/OLE parts are byte-identical, and the original DOC hash matches.
Review changed PNG pages 3, 5, 6, 8, 9, 14–18 and 22; all other pages equal the
previously inspected output. All five numeric/°С pairs on the relevant PDF page
are on the same line. All four continuation captions pass the final-PDF guard;
main prose still has 1.5 spacing. Publish new unique DOCX/review files in the
same document chat via the authorized CLI workspace path, with verified
FileReceipts and output_files visibility. Do not overwrite originals or previous
outputs. Preserve prior manual-review and missing-GOST-font disclosures.

Validation: 410 application tests pass, ten optional tests skipped, existing
PyPDF2 deprecation warning unchanged. Three prepared-runtime tests also pass:
end-of-line value/unit placement across bold/plain runs on deliberately narrow
lines (four actual pairs), four-level list geometry, and complete export.
Strict mypy passes all 44 hardened modules. Read-only doctor is ready with
intact SQLite/Chroma and local Ollama; deterministic retrieval recall@1 is 1.0.
Private QA files/receipts stay in ignored eval-results/unit-spacing-2026-11-17/.
The unrelated user change in hybrid_retriever.py remains outside the commit.

### 2026-11-18 — Supplied ГОСТ 2.114 TU checklist and request-owned form

Read the complete supplied 15-page ГОСТ 2.114-2016 edition (December 2018
reprint; 2019 publication details), including conditions, notes and dependencies.
Add a separate, non-executable review registry and human-readable checklist:
88 numbered positions in sections 4–6, including seven structural headings,
map to 148 review items; sections 1–3 and all source pages are accounted for
separately. Every normative paragraph has an item; split the substantial lists
into concrete review subjects. Retain exact source/page-text hashes and source
span boundaries/hashes, including continuations across pages. `tu_requirements`
verifies the full paragraph/span inventory against the existing immutable archive.
This is an evidence navigation check, not semantic/conformity proof or a count
of fulfilled requirements. Keep the wider semantic catalog explicitly incomplete.
Record the source's dated references/footnote editions; do not silently substitute
new supplied standards or claim current legal applicability.

148 items distinguish requirement/recommendation/permission, explicit conditions,
paper/electronic alternatives, referenced documents, available limited code
assistance, candidate observations and specific human checks. Ten items relate
to existing limited observations/formatting capabilities; 138 have no specialized
automation. All normative outcomes remain pending human judgment. Do not infer
absence of safety content from a missing heading, invent guarantees/technical
norms or generate decisions/signatures. Keep 5.1.2 developer/TZ exceptions and
5.7.16 external methods explicit. Existing dimensions/headings/reference checks
remain scoped observations, not complete engineering or approval validation.

Integrate the separate review into CoverageReport and exact-candidate approval.
Add JSON serialization for typed review models and a --form CLI option. Preserve
the 35 original registry entries/17 selected formatting entries separately;
no formatting recipe, renderer code, Docker image, Chroma or model is changed.
Capture document_form per request: unconfirmed by default, print_framed,
print_frameless or electronic. Enable the form selector only for explicitly
selected TU kind. Pass it through the GUI worker/jobs/coverage/approval, reject
invalid combinations before conversion and stale chat/attachment dialogs.
The selector scopes the checklist only; it does not create formal electronic KD
or remove artwork. User explicitly chose a print layout with frames/stamps for
the current private TU; future requests retain their own default/selection.

Apply the read-only review to the previous published private TU SHA-256
b292617c0c9e1d7b71cf3670864757bbb9b108e333430c7e1a03316a84f7217f.
The archive inventory matches; six rows concern unselected form alternatives.
Publish a new report in that chat's results with verified FileReceipt/readback
and output_files visibility. Prior DOCX/source/originals remain unchanged.
Priorities: obtain referenced OTU/main KD and TZ/developer composition decision;
check ordering example and equipment substitution/arbitration details; validate
content, metrology and actual approvals manually. The visible PDF's absence of
the arbitration term is only a navigation finding, not proof of violation.
No new DOCX render/native GUI interaction pass is claimed in this read-only stage.
Private findings, CLI JSON, evidence and receipts stay in ignored
`eval-results/tu-2114-review-2026-11-18/` and chat results; never commit them.

Validation: 424 application tests pass, 11 optional tests skipped, with the
existing PyPDF2 deprecation warning. The TU review module's 15 tests also pass
with BUTUZ_STANDARDS_LIVE=1, including exact local archive verification, source
changes/omitted-clause rejection, form-scoped evidence and exact-byte binding.
Synthetic tests cover malicious/invalid catalog claims, conditions, missing
sources, typed JSON, GUI callbacks, stale dialogs, and rejection without
publication. Actual CLI JSON exports all 148 items for the private candidate.
Strict mypy passes all 45 hardened modules and desktop syntax compilation passes.
Read-only doctor is ready/intact; deterministic retrieval recall@1 is 1.0.

### 2026-11-18 — Selected Р 2.105 text structures and twelve-source TU order

Review scope pages for every supplied edition and record a source/hash-pinned
TU application order in standard_scopes / tu_source_scopes.json. Expose the
current stage and next action in TU coverage. Distinguish textual formatting,
document composition, diagram kinds, electrical designations, assembly/harness
drawings and operating-document rules. This is scope review, not a complete
clause inventory or automatic applicability service; only the two-source recipe
enables transformations. Changed editions stay explicitly unreviewed. Preserve
the separate 148-item ГОСТ 2.114 checklist and pending engineering decisions.

Add four evidence entries and select them plus the existing body-font entry:
39 registry records, 22 recipe selections. text_structures handles existing,
unambiguous TOC1/2 entries/bookmarks with dotted leaders and hanging wrapped
titles; recognized three-line appendix headings; smaller note typography and
tracked labels; explicit smaller bold-italic examples. Set recognized main
prose/introduction to 14 pt, notes/examples to 12 pt, retaining main 1.5 line
spacing, font families, inline emphasis and superscripts. Do not reinterpret
ordinary mentions, invent missing sections, rewrite punctuation, alter counters
or process opaque fields/objects as prose. Preserve measured figure-note groups.
For label tracking, an exact source-index TextSplit ledger permits only one
literal node's nonempty unchanged partition; the general text guard remains
strict, followed by the separate existing NBSP ledger. Ambiguity stays visible.

Add the helper and evidence to Docker COPY/allowlist and runtime fingerprint.
Explicitly update the already prepared local document image offline over its
existing immutable base; no downloads, host converters or models are involved.
Prepare a fresh copy of the private TU from its original DOC: 24 pages,
20 TOC entries, 12 note paragraphs, two appendix headings, zero examples.
Inspect all twelve changed pages individually (2, 3, 4, 6, 15–21, 23);
the other twelve PNGs equal the previously reviewed export. Four continuation
captions pass the final PDF guard. All 1027 paragraph texts/field instructions,
the numbering part and ten opaque media/OLE parts match the prior result;
original DOC hash is unchanged. Keep the inherited Liberation Sans display-copy
disclosure and original image parts. Leave note/list punctuation and engineering
content for explicit review. Publish unique DOCX and detailed review files in
the existing chat results with verified readback/FileReceipts/output_files;
originals and previous results remain untouched. Private QA is ignored under
eval-results/gost-text-2026-11-18/. Native GUI/Word interaction is not claimed.

Validation: 444 application tests pass, 12 optional tests skipped; existing
PyPDF2 deprecation warning remains. Four prepared-runtime tests pass for TOC
wrapping/note font sizes, list continuation geometry, numeric-unit binding and
complete document export; two local HTTP cancellation tests also pass. The
initial restricted run could not bind its loopback fixture; the complete rerun
with local access passes. Strict mypy passes 47 hardened modules. Read-only
doctor is ready/intact; deterministic retrieval recall@1 is 1.0.

Remaining stages are explicit in docs/gost-application-order.md: finish the
unimplemented conditions/structures of Р 2.105, then recognized Р 2.104 stamp
forms/requisites and the genuinely applicable parts of the other sources.
No claim that all twelve standards or the complete TU are automatically compliant.

### 2026-11-18 — Р 2.105 table labels, numeric columns and remaining-rule review

Review the supplied clauses for references, formulas, footnotes, terminology,
quantities, title/approval sheets and conditional document structures. Add nine
scoped evidence records (48 total); select two new deterministic operations
(24 selections): track the existing literal table label through the exact
TextSplit ledger; center only unambiguous unmerged numeric columns. Preserve
text, precision, numbering, merges, opaque parts and unsupported layouts.

Add source-pinned read-only text_review observations to TU coverage: literal
internal references vs recognized caption/appendix targets; explicit hidden
text/TOC/fields/revisions/drawings excluded. Unresolved may be external, never
an automatic violation. Native formula/footnote counts do not establish absence
in images. Remaining meaning, references/editions, title/approval/engineering
content and conditional books/columnar/duplex rules stay specific manual items;
these grouped records are not a complete clause-by-clause inventory.

Rebuild the fixed local document image offline over the existing prepared base.
Fresh export of the original private TU remains 24 pages: five table labels;
references resolve to five tables, one figure and two appendices, with no
recognized duplicates or missing literal local targets. Review changed pages
4, 5, 7, 9, 10, 22; all other pages equal the previous inspected export. Full
application suite passes 448 tests, 12 optional skips, existing PyPDF2 warning.
Strict types pass the four changed helpers. Private QA stays ignored under
eval-results/gost-rules-2026-11-18/. Proceed to existing-frame/stamp measurements
without replacing original artwork or inventing requisites.

### 2026-11-18 — Existing Р 2.104 stamp and rendered-frame observations

Add read-only stamp_review to TU coverage only with the matching archived
Р 2.104 source. Resolve anchor/group scales for supported non-rotated DrawingML
outlines in referenced active headers. Disclose unsupported child groups;
never infer complete form/field conformity, signatures, dates or line-type
compliance from partial measurements. Preserve every existing drawing position.
Record table 1 paper date exceptions for fields 13/18/20/23; a two-digit year
alone is not a failure. Unknown/VML/opaque/ambiguous/rotated geometry stays manual.

Add frame_preview observations on the exact final PDF in prepare_document,
after the existing continuation-caption guard and before approval/publication.
Recognize only unambiguous closed axis-aligned vector A4 contours; disclose
unmeasured pages and unknown forms. Do not identify the change-registration
sheet as a normal 2/2а stamp from an arbitrary table line. Keep this host-side
read-only PDF analysis distinct from the isolated converter and fixed-image
fingerprint; no host converter, executable user code or new download is used.
The image is explicitly refreshed offline for the updated source evidence.

The private TU reveals actual legacy template scale differences: rendered
page 2 outline width 183.427 mm, lower block 40.022 mm; pages 3–23 width
181.275 mm, lower block 14.764 mm. The recognized DrawingML first-stamp group
independently measures 183.439 mm / 40.06 mm with partial child geometry.
Compare conditionally to forms 2/2а 185 mm / 40 or 15 mm, not to an invented
normative tolerance. No artwork stretching/replacement is attempted: precise
normalization still requires a separately reviewed template/explicit decision
to replace legacy graphics, outside the current preserve-geometry profile.

Fresh final TU export remains 24 pages. All PNGs equal the inspected export:
six changed pages (4, 5, 7, 9, 10, 22), eighteen equal prior reviewed output.
All 1027 paragraph texts/field instructions, numbering and ten media/OLE parts
match. Header/footer geometry and relationships match; a fresh legacy import
changes only one numeric OLE ObjectID in header2.xml. QA permits exactly that
known import identity difference, not arbitrary header/text normalization;
no runtime preservation guard is relaxed. Original DOC hash remains unchanged.
Publish unique DOCX and detailed review in existing chat results with exact-byte
FileReceipts/output_files, including all warnings and source-scoped coverage.
Private artifacts remain ignored under eval-results/gost-rules-2026-11-18/.

Validation: full suite 457 passed, 12 optional skipped; existing PyPDF2 warning.
Focused frame/stamp/text/scope checks pass all 16 after the final conservative
unknown-group adjustment. Four prepared-runtime tests pass: TOC/note typography,
list wrapping, numeric-unit wrapping and complete export. Strict mypy passes
50 hardened modules; read-only doctor ready/intact, deterministic recall@1 1.0.
No native GUI/Word interaction or full GOST conformity is claimed. Update the
source application order to distinguish implemented operations, observations,
remaining engineering review and the unprepared exact-geometry template.
