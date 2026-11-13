"""Bound request history without changing persisted chat messages."""
from __future__ import annotations

from typing import Any


def recent_history(history: list[dict[str, Any]] | None, *, max_chars: int = 3000) -> list[dict[str, str]]:
    """Retain newest complete turns first, keeping recent code intact when it fits.

    Never silently present a cut code block as a complete source file. A single
    oversized turn is explicitly marked; the full original remains in storage.
    """
    if max_chars <= 0:
        return []
    selected: list[dict[str,str]] = []
    used = 0
    for item in reversed((history or [])[-8:]):
        content = str(item.get('content',''))
        if used+len(content)>max_chars:
            if selected:
                break
            notice = '\n[Предыдущее сообщение сокращено для контекста; это не полный исходный код.]\n'
            if max_chars<len(notice):
                selected.append({'role':str(item.get('role','assistant')),'content':'[Сокращено]'[:max_chars]})
                break
            available = max(0,max_chars-len(notice))
            head = available//2
            content = content[:head]+notice+(content[-(available-head):] if available-head else '')
        selected.append({'role':str(item.get('role','assistant')),'content':content})
        used += len(content)
    return list(reversed(selected))
