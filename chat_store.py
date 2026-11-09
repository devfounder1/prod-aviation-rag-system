"""Transactional chat history. Legacy JSON is imported once and never overwritten."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any
import uuid

BASE_DIR = Path(__file__).resolve().parent
Chat = dict[str, Any]


class HistoryMigrationError(ValueError):
    """Legacy history cannot be safely imported; no empty replacement is created."""


class ChatStore:
    def __init__(self, db_path: Path, legacy_path: Path) -> None:
        self.db_path = db_path.resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError(f"Unsupported chat database version: {version}")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS chats (position INTEGER PRIMARY KEY AUTOINCREMENT, "
                       "id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL CHECK(json_valid(payload)))")
            db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("PRAGMA user_version=1")
        self._import_legacy(legacy_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.db_path, timeout=15)
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _import_legacy(self, path: Path) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM metadata WHERE key='legacy_import_v1'").fetchone():
                return
            raw = path.read_bytes() if path.exists() else None
            history: dict[str, Chat] = {}
            if raw is not None:
                try:
                    history = json.loads(raw)
                    if not isinstance(history, dict):
                        raise ValueError("Expected an object keyed by chat ID")
                    for key, chat in history.items():
                        if (not isinstance(key, str) or not key or not isinstance(chat, dict)
                                or not isinstance(chat.get("name"), str)
                                or not isinstance(chat.get("messages"), list)):
                            raise ValueError(f"Invalid chat: {key}")
                        for msg in chat["messages"]:
                            if (not isinstance(msg, dict) or not isinstance(msg.get("role"), str)
                                    or not isinstance(msg.get("content"), str)):
                                raise ValueError(f"Invalid message in chat: {key}")
                except (ValueError, UnicodeError) as exc:
                    raise HistoryMigrationError(f"Cannot import {path}; original preserved: {exc}") from exc
                digest = hashlib.sha256(raw).hexdigest()
                backup = self.db_path.parent / "backups" / f"chats_history-{digest}.json"
                backup.parent.mkdir(parents=True, exist_ok=True)
                if not backup.exists():
                    with backup.open("xb") as file:
                        file.write(raw)
                        file.flush()
                        os.fsync(file.fileno())
                if backup.read_bytes() != raw:
                    raise HistoryMigrationError("Legacy backup verification failed")
            else:
                digest = "absent"
            for chat_id, chat in history.items():
                db.execute("INSERT INTO chats(id,payload) VALUES (?,?)",
                           (chat_id, json.dumps(chat, ensure_ascii=False)))
            # Verify complete contents (including optional fields) before committing the marker.
            imported = {row[0]: json.loads(row[1]) for row in db.execute("SELECT id,payload FROM chats")}
            if imported != history:
                raise HistoryMigrationError("Chat migration verification failed")
            db.execute("INSERT INTO metadata VALUES ('legacy_import_v1',?)", (digest,))

    def snapshot(self) -> dict[str, Chat]:
        with self._connect() as db:
            return {row[0]: json.loads(row[1]) for row in
                    db.execute("SELECT id,payload FROM chats ORDER BY position")}

    def create(self, name: str) -> str:
        chat_id = uuid.uuid4().hex
        with self._connect() as db:
            db.execute("INSERT INTO chats(id,payload) VALUES (?,?)",
                       (chat_id, json.dumps({"name": name, "messages": []}, ensure_ascii=False)))
        return chat_id

    def delete(self, chat_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM chats WHERE id=?", (chat_id,))

    def update(self, chat_id: str, change: Callable[[Chat], None]) -> bool:
        """Read latest state and modify one chat within the same write transaction."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM chats WHERE id=?", (chat_id,)).fetchone()
            if row is None:
                return False  # A late worker must not resurrect a deleted chat.
            chat = json.loads(row[0])
            change(chat)
            db.execute("UPDATE chats SET payload=? WHERE id=?",
                       (json.dumps(chat, ensure_ascii=False), chat_id))
            return True

    def backup(self, destination: Path) -> None:
        """Create a consistent, standalone SQLite snapshot, including WAL contents."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb"):
            pass  # Refuse to overwrite existing files, especially the live database.
        with self._connect() as source:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Chat backup integrity check failed")
            finally:
                target.close()


class ChatManager:
    def __init__(self, filename: str | Path = BASE_DIR / "chats_history.json",
                 db_path: str | Path = BASE_DIR / "data" / "chats.sqlite3") -> None:
        self.store = ChatStore(Path(db_path), Path(filename))
        self._lock = threading.RLock()
        self.current_chat_id: str | None = None
        chats = self.chats
        if chats:
            self.current_chat_id = next(reversed(chats))
        else:
            self.create_new_chat()

    @property
    def chats(self) -> dict[str, Chat]:
        """Detached read snapshot. Persist changes through explicit mutation methods."""
        return self.store.snapshot()

    def create_new_chat(self, name: str = "Новый чат") -> str:
        with self._lock:
            chat_id = self.store.create(name)
            self.current_chat_id = chat_id
            return chat_id

    def delete_chat(self, chat_id: str) -> None:
        with self._lock:
            self.store.delete(chat_id)
            if self.current_chat_id == chat_id:
                remaining = self.chats
                self.current_chat_id = next(iter(remaining), None)
                if self.current_chat_id is None:
                    self.create_new_chat()

    def rename_chat(self, chat_id: str, new_name: str) -> None:
        self.store.update(chat_id, lambda chat: chat.update(name=new_name))

    def get_current_chat(self) -> Chat | None:
        with self._lock:
            return self.chats.get(self.current_chat_id) if self.current_chat_id else None

    def add_message(self, role: str, content: str, attachments: list[str] | None = None,
                    sources: list[str] | None = None, chat_id: str | None = None) -> bool:
        with self._lock:
            target = chat_id or self.current_chat_id
            if target is None:
                return False
            message = {"role": role, "content": content, "attachments": attachments or [],
                       "sources": sources or []}
            return self.store.update(target, lambda chat: chat["messages"].append(message))

    def add_attachment(self, filename: str, chat_id: str | None = None) -> None:
        with self._lock:
            target = chat_id or self.current_chat_id
            def change(chat: Chat) -> None:
                attachments = chat.get("attachments") or []
                if filename not in attachments:
                    attachments.append(filename)
                chat["attachments"] = attachments
            if target:
                self.store.update(target, change)

    def remove_attachment(self, filename: str) -> None:
        with self._lock:
            def change(chat: Chat) -> None:
                chat["attachments"] = [name for name in chat.get("attachments", []) if name != filename]
            if self.current_chat_id:
                self.store.update(self.current_chat_id, change)

    def switch_chat(self, chat_id: str) -> None:
        with self._lock:
            if chat_id in self.chats:
                self.current_chat_id = chat_id
