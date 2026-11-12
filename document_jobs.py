"""Request-owned preparation, review and publication of an exact DOCX candidate."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile
import uuid

from activity import ActivityEvent
from document_runner import DocumentCandidate, prepare_document
from file_receipts import FileReceipt, receipt_summary, verified_receipt
from file_tools import prepare_attachments, workspace_for_chat


@dataclass(frozen=True)
class DocumentProposal:
    path: str
    candidate: DocumentCandidate

    def description(self) -> str:
        return (f'Создать DOCX\nПуть: {self.path}\nРазмер: {len(self.candidate.docx)} байт\n'
                f'SHA-256: {hashlib.sha256(self.candidate.docx).hexdigest()}\n\n'
                + self.candidate.description())


@dataclass(frozen=True)
class DocumentOutcome:
    receipt: FileReceipt | None
    description: str

    def render(self) -> str:
        return ((receipt_summary([self.receipt]) + '\n\n') if self.receipt is not None else '') + self.description


def create_document(chat_id: str, attachment: dict[str, str],
                    approve: Callable[[DocumentProposal], bool],
                    cancel: dict[str, bool] | None = None,
                    on_activity: Callable[[ActivityEvent], None] | None = None) -> DocumentOutcome:
    def active() -> None:
        if cancel and cancel.get('cancelled'):
            raise RuntimeError('Обработка документа отменена')

    active()
    root = workspace_for_chat(chat_id).resolve()
    original = Path(attachment['path']).resolve(strict=True)
    if original.suffix.lower() not in {'.doc', '.docx'}:
        raise ValueError('Для оформления выберите DOC или DOCX; PDF пока не поддерживается этим действием')
    registered = prepare_attachments(chat_id, [attachment])
    source = root / 'attached' / original.name
    source_hash = registered[original.name][1]
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
        raise ValueError('Копия вложения изменилась; прикрепите файл повторно')
    if on_activity:
        on_activity(ActivityEvent('working', 'Оформляю документ и готовлю страницы для проверки', 'AGENT'))
    candidate = prepare_document(source, cancel)
    active()
    stem = original.stem.strip(' .')[:100] or 'Документ'
    path = root / 'results' / (stem + '_ГОСТ_' + uuid.uuid4().hex[:8] + '.docx')
    if not path.resolve().is_relative_to(root):
        raise ValueError('Папка результатов вышла за рабочую папку чата')
    proposal = DocumentProposal(str(path), candidate)
    if on_activity:
        on_activity(ActivityEvent('approval', 'Проверьте страницы и подтвердите сохранение', 'AGENT'))
    if not approve(proposal):
        return DocumentOutcome(None, 'Сохранение отменено. Исходный документ не изменён.')
    active()
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
        raise ValueError('Копия вложения изменилась во время проверки; результат не сохранён')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or not path.resolve().is_relative_to(root):
        raise ValueError('Путь результата изменился во время подтверждения')
    fd, temporary = tempfile.mkstemp(prefix='.gost-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(candidate.docx); stream.flush(); os.fsync(stream.fileno())
        active()
        if not path.resolve().is_relative_to(root) or path.exists():
            raise ValueError('Путь результата изменился')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    receipt = verified_receipt(path, candidate.docx, str(path.relative_to(root)))
    return DocumentOutcome(receipt, 'Сохранён редактируемый проект DOCX.\n\n' + candidate.description())
