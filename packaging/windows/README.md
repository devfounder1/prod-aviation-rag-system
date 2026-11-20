# Windows x64 handoff

This is an **assembly recipe**, not a claim that a Windows application was tested.
The development host is macOS. Native GUI acceptance remains pending.

1. Generate the maintained manual: bundled Python + tools/build_user_guide.py.
2. Build a source kit: `uv run python packaging/windows/make_source_kit.py dist/windows-source-kit`.
3. On a Windows x64 preparation machine supply full portable CPython 3.12,
   matching full Flet Windows client, standalone Ollama, local HF/Ollama models,
   approved standards v1 archive and both Linux amd64 Docker image tar files.
4. Run Tools/Build-Windows.ps1 with the exact paths in the manual. The output
   must be NEW; no user-history or index directories are copied from the repository.
5. Run Tools/Check-Offline.ps1, then ALL disconnected GUI acceptance cases in
   docs/user-guide-ru.md section 24. Keep the complete runtime directory together.

The GitHub workflow Windows launcher and assembly scripts runs on relevant release
pushes or manual dispatch. It parses
PowerShell, compiles the C# launcher and tests pure portable logic on Windows.
Its artifact is ONLY the launcher. It contains neither Python nor Flet, models,
Docker/WSL nor private documents and cannot run alone.

The launcher fixes its working directory to App, logging to Logs/launcher.log.
windows_entry sets portable local model caches, verifies Flet presence/version
and configures offline operation before imports. Existing data stays in App/data
and App/agent_workspace. Never build over an installed user's folder.

Models, original standards PDFs and runtime dependencies have their own licenses.
No automatic downloads occur at GUI runtime; network access during a preparation
build is explicit unless Wheelhouse is supplied. Docker/WSL and system drivers
must be prepared separately. See the complete Russian DOCX/Markdown manual.
