# Production hardening progress

The application remains local: Ollama, CHAT/SEARCH/AGENT, two collections in one Chroma, SQLite chat history.

- [ ] 0. Repository hygiene: exclude private runtime data; publish source branch.
- [ ] 1. Router: constrained intent output, validation and safe fallback.
- [ ] 2. Jobs: per-request cancellation and stale UI callback protection.
- [ ] 3. Tools: per-chat workspace and per-request attachment/approval context.
- [ ] 4. RAG evaluation: reproducible corpus, expected sources and abstention metrics.
- [ ] 5. Release checks: offline diagnostics, log rotation, CI and recovery instructions.

Passing these checks does not certify model answer correctness or safe execution of arbitrary code. Host Python execution remains disabled for the universal agent.
