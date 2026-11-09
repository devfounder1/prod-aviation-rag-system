"""One persistent Chroma client; verified, repeatable import of legacy indexes.

Legacy directories are never opened by Chroma: migration operates on snapshots.
Run with the old application stopped.
"""
from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from config import settings

_lock = threading.RLock()
_client: Any = None


def migrate_legacy(client: Any, destination: Path) -> dict[str, int]:
    """Copy original vectors and metadata without re-embedding or deleting sources."""
    marker = destination / "migration-v1.json"
    if marker.exists():
        return json.loads(marker.read_text())
    result: dict[str, int] = {}
    sources = [
        (Path(settings.legacy_chroma_dir), "PRL27_technical_docs_children", settings.knowledge_collection),
        (Path(settings.legacy_chroma_dir).parent / "user_docs_chroma", "user_documents", settings.user_docs_collection),
    ]
    for source, old_name, new_name in sources:
        if not (source / "chroma.sqlite3").exists():
            continue
        if source.resolve() == destination.resolve():
            raise ValueError("Choose a new CHROMA_PERSIST_DIR; legacy data must remain separate")
        snapshot = destination.parent / "legacy_snapshots" / source.name
        if not snapshot.exists():
            temporary = snapshot.with_name(snapshot.name + ".partial")
            if temporary.exists():
                shutil.rmtree(temporary)
            shutil.copytree(source, temporary)
            temporary.rename(snapshot)
        legacy = chromadb.PersistentClient(path=str(snapshot), settings=ChromaSettings(anonymized_telemetry=False))
        names = [c if isinstance(c, str) else c.name for c in legacy.list_collections()]
        if old_name not in names:
            if names:
                raise RuntimeError(f"Unexpected legacy collections in {source}: {names}")
            continue
        original = legacy.get_collection(old_name, embedding_function=None)
        target = client.get_or_create_collection(new_name, embedding_function=None,
                                                metadata=original.metadata)
        for offset in range(0, original.count(), 200):
            batch: Any = original.get(limit=200, offset=offset,
                                 include=["embeddings", "documents", "metadatas"])
            payload = {key: batch[key] for key in ("ids", "embeddings", "documents", "metadatas")
                       if batch.get(key) is not None}
            target.upsert(**payload)
            copied: Any = target.get(ids=batch["ids"], include=["embeddings", "documents", "metadatas"])
            indexed = {key: i for i, key in enumerate(copied["ids"])}
            for i, key in enumerate(batch["ids"]):
                j = indexed[key]
                for field in ("documents", "metadatas", "embeddings"):
                    if batch.get(field) is not None:
                        left, right = batch[field][i], copied[field][j]
                        if field == "embeddings":
                            import numpy as np
                            equal = np.allclose(left, right)
                        else:
                            equal = left == right
                        if not equal:
                            raise RuntimeError(f"Migration verification failed: {old_name}/{key}/{field}")
        result[new_name] = original.count()
        if old_name == "PRL27_technical_docs_children":
            parents = snapshot / "parent_docs"
            if parents.exists():
                for file in parents.glob("*.json"):
                    target_file = destination / "parent_docs" / file.name
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    if target_file.exists() and target_file.read_bytes() != file.read_bytes():
                        raise RuntimeError(f"Parent document conflict: {file.name}")
                    shutil.copy2(file, target_file)
    temp = marker.with_suffix(".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    temp.replace(marker)
    return result


def get_chroma_client() -> Any:
    global _client
    with _lock:
        if _client is None:
            destination = Path(settings.chroma_persist_dir)
            destination.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(destination), settings=ChromaSettings(anonymized_telemetry=False))
            migrate_legacy(client, destination)
            _client = client
        return _client


if __name__ == "__main__":
    client = get_chroma_client()
    for name in (settings.knowledge_collection, settings.user_docs_collection):
        coll = client.get_or_create_collection(name, embedding_function=None)
        print(f"{name}: {coll.count()} chunks")
