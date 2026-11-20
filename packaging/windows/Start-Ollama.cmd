@echo off
setlocal
cd /d "%~dp0.."
set "OLLAMA_MODELS=%CD%\Models\ollama"
set "OLLAMA_HOST=127.0.0.1:11434"
set "OLLAMA_NO_CLOUD=1"
"%CD%\Ollama\ollama.exe" serve
pause
