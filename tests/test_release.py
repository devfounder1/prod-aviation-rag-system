from pathlib import Path
import sqlite3
import httpx
from doctor import check, inspect_sqlite
from config import settings


def test_diagnostics_reports_missing_model_without_inference() -> None:
    seen = []
    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={'data': []})
    result = check(httpx.MockTransport(respond), check_cache=False)
    assert not result['ready']
    assert result['checks']['ollama']['selected_model_installed'] is False
    assert seen == [settings.llm_base_url + '/models']


def test_diagnostics_detects_corrupt_sqlite(tmp_path: Path) -> None:
    path = tmp_path / 'broken.sqlite3'
    path.write_bytes(b'not a database')
    assert inspect_sqlite(path, {'chats'})['status'] == 'error'


def test_log_rotation_bounds_retention(tmp_path: Path) -> None:
    import logging
    from logging_config import rotating_handler
    handler = rotating_handler(tmp_path / 'app.log', max_bytes=100, backup_count=2)
    logger = logging.Logger('rotation-test')
    logger.addHandler(handler)
    for _ in range(20):
        logger.info('x' * 60)
    handler.close()
    assert len(list(tmp_path.glob('app.log*'))) <= 3


def test_missing_vision_model_warns_without_disabling_text_chat() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'data': [{'id': settings.llm_model_name}]})
    result = check(httpx.MockTransport(respond), check_cache=False)
    assert result['checks']['ollama']['status'] == 'ok'
    assert result['checks']['vision']['status'] == 'warning'
    assert result['checks']['vision']['configured_model_installed'] is False
