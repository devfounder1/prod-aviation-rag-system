"""Read-only local readiness checks. Never downloads or starts a model."""
from __future__ import annotations
import argparse
import importlib.metadata
import json
from pathlib import Path
import sqlite3
from typing import Any
import httpx
from config import settings

BASE = Path(__file__).resolve().parent


def inspect_sqlite(path: Path, required: set[str]) -> dict[str, Any]:
    if not path.exists():
        return {'status': 'warning', 'detail': 'Not initialized; migration runs on first use'}
    try:
        with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=3) as db:
            integrity = db.execute('PRAGMA quick_check').fetchone()[0]
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            valid = integrity == 'ok' and required.issubset(tables)
            return {'status': 'ok' if valid else 'error', 'integrity': integrity,
                    'required_tables_present': required.issubset(tables)}
    except sqlite3.Error as exc:
        return {'status': 'error', 'detail': type(exc).__name__}


def local_model_cache(repo_id: str, required: bool) -> dict[str, Any]:
    from huggingface_hub import snapshot_download
    try:
        path = Path(snapshot_download(repo_id, local_files_only=True))
        weights = any(p.is_file() for pattern in ('*.safetensors', '*.bin', '*.onnx') for p in path.rglob(pattern))
        return {'status': 'ok' if weights else ('error' if required else 'warning'),
                'cached_weights': weights}
    except Exception as exc:
        return {'status': 'error' if required else 'warning', 'detail': type(exc).__name__}


def check(transport: httpx.BaseTransport | None = None, check_cache: bool = True) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for package in ('flet', 'flet-cli', 'flet-desktop', 'torch', 'chromadb', 'langchain-openai'):
        if package == 'flet-desktop':
            import platform
            if platform.system() == 'Linux':
                package = 'flet-desktop-light'
        try:
            checks[package] = {'status': 'ok', 'version': importlib.metadata.version(package)}
        except importlib.metadata.PackageNotFoundError:
            checks[package] = {'status': 'error', 'detail': 'Run uv sync --locked'}
    try:
        with httpx.Client(transport=transport, timeout=3, trust_env=False, follow_redirects=False) as client:
            response = client.get(settings.llm_base_url + '/models')
            response.raise_for_status()
            models = [m['id'] for m in response.json().get('data', [])]
            checks['vision'] = {'status': 'ok' if settings.vision_model_name in models else 'warning',
                                'configured_model_installed': settings.vision_model_name in models}
            checks['ollama'] = {'status': 'ok' if settings.llm_model_name in models else 'error',
                                'selected_model_installed': settings.llm_model_name in models,
                                'detail': 'Start ollama serve; install/select a model before runtime' if settings.llm_model_name not in models else 'Local endpoint ready'}
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        checks['ollama'] = {'status': 'error', 'detail': type(exc).__name__ + ': start ollama serve'}
    if check_cache:
        checks['embeddings'] = local_model_cache(settings.embedder_model_name, required=True)
        checks['reranker'] = local_model_cache('BAAI/bge-reranker-v2-m3', required=False)
    checks['chat_history'] = inspect_sqlite(BASE / 'data/chats.sqlite3', {'chats', 'metadata'})
    checks['chroma'] = inspect_sqlite(Path(settings.chroma_persist_dir) / 'chroma.sqlite3', {'collections'})
    path = Path(settings.chroma_persist_dir) / 'chroma.sqlite3'
    if path.exists() and checks['chroma']['status'] == 'ok':
        with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            names = {row[0] for row in db.execute('SELECT name FROM collections')}
        expected = {settings.knowledge_collection, settings.user_docs_collection}
        checks['chroma']['collections_present'] = expected.issubset(names)
        if not expected.issubset(names):
            checks['chroma']['status'] = 'error'
    return {'ready': all(c['status'] != 'error' for c in checks.values()), 'checks': checks}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-cache', action='store_true')
    args = parser.parse_args()
    report = check(check_cache=not args.skip_cache)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report['ready'] else 1)
