"""Trusted write receipts are tool artifacts, never model-authored success claims."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path


@dataclass(frozen=True)
class FileReceipt:
    path: str
    display_path: str
    sha256: str
    byte_count: int
    python_checked: bool
    original: bool = False

    def still_matches(self) -> bool:
        try:
            return hashlib.sha256(Path(self.path).read_bytes()).hexdigest() == self.sha256
        except OSError:
            return False


def verified_receipt(path: Path, expected: bytes, display_path: str, original: bool = False) -> FileReceipt:
    actual = path.read_bytes()
    if actual != expected:
        raise OSError('Файл после записи не совпал с подтверждённым содержимым')
    return FileReceipt(str(path), display_path, hashlib.sha256(actual).hexdigest(), len(actual),
                       path.suffix.lower() == '.py', original)


def receipt_summary(receipts: list[FileReceipt]) -> str:
    latest = {receipt.path: receipt for receipt in receipts}
    lines = ['Проверенные результаты записи:']
    for receipt in latest.values():
        if not receipt.still_matches():
            lines.append(f'⚠️ `{receipt.display_path}` — файл изменён или недоступен после записи.')
            continue
        location = 'оригинал' if receipt.original else '«Файлы чата»'
        lines.append(f'📄 `{receipt.display_path}` — сохранён, запись проверена; {location}.')
    if any(receipt.python_checked for receipt in latest.values()):
        lines.append('Синтаксис Python проверен. Код и тесты не запускались.')
    return '\n'.join(lines)
