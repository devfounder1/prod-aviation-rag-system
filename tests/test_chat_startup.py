"""Starting the desktop must display persisted chats without creating another."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chat_store import ChatManager


def test_startup_restores_sidebar_and_current_messages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import prilozhenie

    legacy = tmp_path / 'legacy.json'
    database = tmp_path / 'chats.sqlite3'
    manager = ChatManager(filename=legacy, db_path=database)
    first = manager.current_chat_id
    manager.add_message('user', 'Первый вопрос')
    second = manager.create_new_chat()
    manager.add_message('user', 'Последний вопрос')
    manager.add_message('assistant', 'Сохранённый ответ')
    reopened = ChatManager(filename=legacy, db_path=database)
    before = reopened.chats
    monkeypatch.setattr(prilozhenie, 'ChatManager', lambda: reopened)
    monkeypatch.setattr(prilozhenie.threading.Thread, 'start', lambda _: None)
    monkeypatch.setitem(__import__('sys').modules, 'voice_input', SimpleNamespace(WakeWordListener=MagicMock()))
    monkeypatch.setattr(prilozhenie.AviationRAGApp, '_load_prl_path', lambda _: '/configured')
    monkeypatch.setattr(prilozhenie.ft.Column, 'scroll_to', MagicMock())
    page = MagicMock()
    page.loop.is_closed.return_value = False
    page.loop.is_running.return_value = True
    app = prilozhenie.AviationRAGApp(page)
    assert list(app.chat_list_controls) == [second, first]
    assert reopened.current_chat_id == second
    assert reopened.chats == before
    assert len(app.messages_column.controls) == 2
    assert not app.welcome.visible
    app._shutdown()
