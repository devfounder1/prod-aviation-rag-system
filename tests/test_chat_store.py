from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from chat_store import ChatManager, ChatStore, HistoryMigrationError


@pytest.fixture
def history(tmp_path: Path) -> tuple[Path, Path, dict]:
    source = tmp_path / 'chats_history.json'
    data = {'old-id': {'name': 'Русский чат', 'messages': [
        {'role': 'user', 'content': 'Вопрос', 'sources': ['a.docx'], 'attachments': ['b.pdf'], 'extra': 1}],
        'attachments': ['b.pdf'], 'custom': {'preserve': True}}}
    source.write_text(json.dumps(data, ensure_ascii=False))
    return tmp_path / 'chats.sqlite3', source, data


def test_import_preserves_all_fields_and_original(history: tuple) -> None:
    db, source, expected = history
    raw = source.read_bytes()
    manager = ChatManager(source, db)
    assert manager.chats == expected
    assert source.read_bytes() == raw
    backups = list((db.parent / 'backups').glob('chats_history-*.json'))
    assert len(backups) == 1 and backups[0].read_bytes() == raw
    manager.rename_chat('old-id', 'Renamed')
    manager.add_message('assistant', 'Answer', sources=['manual.docx'])
    assert ChatManager(source, db).chats['old-id']['name'] == 'Renamed'
    assert ChatManager(source, db).chats['old-id']['messages'][-1]['sources'] == ['manual.docx']
    assert source.read_bytes() == raw


def test_once_only_no_resurrection(history: tuple) -> None:
    db, source, _ = history
    manager = ChatManager(source, db)
    manager.delete_chat('old-id')
    source.write_text('corrupted after completed migration')
    assert 'old-id' not in ChatManager(source, db).chats
    assert not manager.add_message('assistant', 'late', chat_id='old-id')
    assert 'old-id' not in manager.chats


@pytest.mark.parametrize('raw', [b'{broken', b'[]', b'{"x":{"name":"bad","messages":[{}]}}'])
def test_bad_legacy_fails_without_empty_history(tmp_path: Path, raw: bytes) -> None:
    source = tmp_path / 'history.json'
    source.write_bytes(raw)
    db = tmp_path / 'chats.sqlite3'
    with pytest.raises(HistoryMigrationError):
        ChatManager(source, db)
    assert source.read_bytes() == raw
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT count(*) FROM chats').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM metadata').fetchone()[0] == 0
    source.write_text('{}')
    assert len(ChatManager(source, db).chats) == 1


def test_concurrent_managers_no_lost_messages(history: tuple) -> None:
    db, source, _ = history
    managers = [ChatManager(source, db) for _ in range(4)]
    def append(i: int) -> None:
        managers[i % 4].add_message('user', str(i), chat_id='old-id')
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(append, range(80)))
    messages = ChatManager(source, db).chats['old-id']['messages']
    assert len(messages) == 81
    assert {m['content'] for m in messages[1:]} == {str(i) for i in range(80)}


def test_switching_and_attachment_mutations(history: tuple) -> None:
    db, source, _ = history
    manager = ChatManager(source, db)
    other = manager.create_new_chat()
    manager.add_message('assistant', 'For original', chat_id='old-id')
    manager.add_attachment('new.pdf', chat_id='old-id')
    assert manager.chats[other]['messages'] == []
    manager.switch_chat('old-id')
    manager.remove_attachment('b.pdf')
    manager.rename_chat('old-id', 'Updated')
    reloaded = ChatManager(source, db).chats['old-id']
    assert reloaded['attachments'] == ['new.pdf']
    assert reloaded['messages'][-1]['content'] == 'For original'
    assert reloaded['custom'] == {'preserve': True}
    detached = manager.get_current_chat()
    detached['messages'].clear()
    assert manager.get_current_chat()['messages']


def test_failed_update_rolls_back(history: tuple) -> None:
    db, source, data = history
    store = ChatStore(db, source)
    def fail(chat: dict) -> None:
        chat['name'] = 'Should never commit'
        raise RuntimeError('simulated error')
    with pytest.raises(RuntimeError):
        store.update('old-id', fail)
    assert store.snapshot() == data


def test_process_crash_rolls_back_and_backup_restores(history: tuple) -> None:
    db, source, data = history
    store = ChatStore(db, source)
    script = '''import os,sqlite3,sys
conn=sqlite3.connect(sys.argv[1])
conn.execute('BEGIN IMMEDIATE')
conn.execute("UPDATE chats SET payload='{}'")
os._exit(17)
'''
    result = subprocess.run([sys.executable, '-c', script, str(db)], check=False)
    assert result.returncode == 17
    assert ChatStore(db, source).snapshot() == data
    backup = db.parent / 'recovery.sqlite3'
    store.backup(backup)
    assert ChatStore(backup, source).snapshot() == data
    with sqlite3.connect(backup) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    with pytest.raises(FileExistsError):
        store.backup(db)
