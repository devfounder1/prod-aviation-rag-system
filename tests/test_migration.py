from pathlib import Path
import hashlib

import chromadb
import pytest
from config import settings
from storage import migrate_legacy


def test_migration_preserves_vectors_parents_and_is_repeatable(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    legacy = tmp_path / "chroma_db_prl27"
    uploads = tmp_path / "user_docs_chroma"
    for directory, name, meta in (
        (legacy, "PRL27_technical_docs_children", {"filename": "manual.pdf", "parent_id": "p"}),
        (uploads, "user_documents", {"filename": "private.txt", "chat_id": "chat-a"}),
    ):
        client = chromadb.PersistentClient(path=str(directory))
        coll = client.create_collection(name, embedding_function=None)
        coll.add(ids=["one"], embeddings=[[1., 0., 0.]], documents=["original text"], metadatas=[meta])
    parents = legacy / "parent_docs"
    parents.mkdir()
    (parents / "p.json").write_text('"parent text"')
    before = {str(f): hashlib.sha256(f.read_bytes()).hexdigest()
              for d in (legacy, uploads) for f in d.rglob("*") if f.is_file()}
    monkeypatch.setattr(settings, "legacy_chroma_dir", str(legacy))
    destination = tmp_path / "unified"
    client = chromadb.PersistentClient(path=str(destination))
    assert migrate_legacy(client, destination) == {"knowledge_base": 1, "attachments": 1}
    assert migrate_legacy(client, destination) == {"knowledge_base": 1, "attachments": 1}
    assert (destination / "parent_docs" / "p.json").read_bytes() == (parents / "p.json").read_bytes()
    assert client.get_collection("attachments").get(where={"chat_id": "other"})["ids"] == []
    for file, digest in before.items():
        assert hashlib.sha256(Path(file).read_bytes()).hexdigest() == digest
    client.get_collection("knowledge_base").delete(ids=["one"])
    assert client.get_collection("attachments").count() == 1
