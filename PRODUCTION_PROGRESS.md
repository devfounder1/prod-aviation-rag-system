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
