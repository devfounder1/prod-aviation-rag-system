"""Bounded document export from a disposable, offline local container."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import struct
import tarfile
import tempfile
import threading
import time
from typing import BinaryIO
import uuid

from sandbox_runner import docker_command

IMAGE = 'butuz-documents:local'
MAX_INPUT = 32 * 1024 * 1024
MAX_EXPORT = 64 * 1024 * 1024


@dataclass(frozen=True)
class DocumentCandidate:
    docx: bytes
    pages: tuple[bytes, ...]
    text: str
    profile: str
    changes: tuple[str, ...]
    warnings: tuple[str, ...]
    legacy_import: bool
    runtime_fingerprint: str = ''

    def description(self) -> str:
        return ('Профиль: ' + self.profile + '\n\nИзменения:\n' + '\n'.join(self.changes)
                + '\n\nТребует проверки:\n' + '\n'.join(self.warnings))


class BoundedProcess:
    """Drain both pipes; cancellation never closes a blocking pipe on the UI loop."""

    def __init__(self, command: list[str], limit: int) -> None:
        env = {k: v for k, v in os.environ.items() if k in {'PATH', 'HOME', 'TMPDIR', 'SYSTEMROOT'}}
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        stdin=subprocess.DEVNULL, env=env)
        self.limit = limit
        self.buffers: list[bytearray] = [bytearray(), bytearray()]
        self.lock = threading.Lock()
        self.overflow = threading.Event()
        self.ready = threading.Event()
        self.threads = [threading.Thread(target=self._read, args=(pipe, n), daemon=True)
                        for n, pipe in enumerate((self.process.stdout, self.process.stderr))]
        for thread in self.threads:
            thread.start()

    def _read(self, pipe: BinaryIO | None, index: int) -> None:
        assert pipe is not None
        while chunk := os.read(pipe.fileno(), 8192):
            with self.lock:
                remaining = self.limit - sum(len(b) for b in self.buffers)
                self.buffers[index].extend(chunk[:max(remaining, 0)])
                if len(chunk) > remaining:
                    self.overflow.set()
                if index == 0 and b'BUTUZ_DOCUMENT_READY\n' in self.buffers[0]:
                    self.ready.set()

    def wait(self, timeout: float, cancel: dict[str, bool] | None, ready: bool = False) -> None:
        deadline = time.monotonic() + timeout
        while True:
            if cancel and cancel.get('cancelled'):
                raise RuntimeError('Обработка документа отменена')
            if self.overflow.is_set():
                raise RuntimeError('Обработчик превысил лимит вывода')
            if ready and self.ready.is_set():
                return
            if self.process.poll() is not None:
                for thread in self.threads:
                    thread.join(2)
                if self.overflow.is_set():
                    raise RuntimeError('Обработчик превысил лимит вывода')
                if self.process.returncode or ready:
                    message = bytes(self.buffers[1]).decode('utf-8', 'replace')[-1800:]
                    raise RuntimeError('Не удалось обработать документ: ' + message)
                return
            if time.monotonic() >= deadline:
                raise RuntimeError('Превышено время обработки документа')
            time.sleep(0.05)

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=5)
        for thread in self.threads:
            thread.join(3)
        for pipe in (self.process.stdout, self.process.stderr):
            if pipe is not None:
                pipe.close()


def decode_export(raw: bytes) -> DocumentCandidate:
    """No extractall: accept only regular, bounded, explicitly named artifacts."""
    if len(raw) > MAX_EXPORT:
        raise ValueError('Слишком большой результат обработки')
    files: dict[str, bytes] = {}
    total = 0
    with tarfile.open(fileobj=BytesIO(raw), mode='r:') as archive:
        for member in archive:
            if member.isdir() and member.name in {'.', './'}:
                continue
            name = member.name.removeprefix('./')
            allowed = name in {'document.docx', 'document.pdf', 'report.json', 'text.txt'} or re.fullmatch(r'page-\d{1,2}\.png', name)
            if not member.isfile() or not allowed or name in files:
                raise ValueError('Недопустимый или повторный файл в результате обработки')
            total += member.size
            if member.size > 32 * 1024 * 1024 or total > MAX_EXPORT:
                raise ValueError('Результат превышает ограничение размера')
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError('Не удалось прочитать результат')
            files[name] = stream.read(member.size + 1)
            if len(files[name]) != member.size:
                raise ValueError('Неполный результат обработки')
    if not {'document.docx', 'document.pdf', 'report.json', 'text.txt'} <= files.keys():
        raise ValueError('Обработчик вернул неполный результат')
    if not files['document.pdf'].startswith(b'%PDF-'):
        raise ValueError('Некорректный PDF предпросмотра')
    if len(files['report.json']) > 100_000 or len(files['text.txt']) > 2_000_000:
        raise ValueError('Слишком большой отчёт предпросмотра')
    report = json.loads(files['report.json'])
    pages = report.get('page_count')
    if type(pages) is not int or not 1 <= pages <= 60:
        raise ValueError('Неверное число страниц предпросмотра')
    names = sorted((n for n in files if n.startswith('page-')), key=lambda n: int(n[5:-4]))
    if len(names) != pages or [int(n[5:-4]) for n in names] != list(range(1, pages + 1)):
        raise ValueError('Отсутствуют страницы предпросмотра')
    if any(not files[n].startswith(b'\x89PNG\r\n\x1a\n') for n in names):
        raise ValueError('Неверный формат страницы предпросмотра')
    for name in names:
        data = files[name]
        if len(data) < 24 or len(data) > 4_000_000 or data[12:16] != b'IHDR':
            raise ValueError('Некорректная страница предпросмотра')
        width, height = struct.unpack('>II', data[16:24])
        if not (1 <= width <= 2000 and 1 <= height <= 2000):
            raise ValueError('Слишком большая страница предпросмотра')
    if report.get('body_text_preserved') is not True or report.get('full_conformance_checked') is not False:
        raise ValueError('Не подтверждена сохранность содержимого или заявлен неподдерживаемый уровень проверки')
    profile = report.get('profile')
    if not isinstance(profile, str) or len(profile) > 300:
        raise ValueError('Неверный профиль оформления')
    fingerprint = report.get('runtime_fingerprint')
    if not isinstance(fingerprint, str) or not re.fullmatch(r'[a-f0-9]{64}', fingerprint):
        raise ValueError('Неизвестная версия обработчика документов')
    for key in ('warnings', 'changes'):
        if not isinstance(report.get(key), list) or not all(isinstance(x, str) and len(x) < 5000 for x in report[key]):
            raise ValueError('Неверный отчёт оформления')
    # Recheck OOXML on the host, but never execute or render it on the host.
    from document_inspection import inspect_docx
    with tempfile.TemporaryDirectory(prefix='butuz-docx-check-') as directory:
        check = Path(directory)/'check.docx'; check.write_bytes(files['document.docx'])
        evidence = inspect_docx(check)
        if evidence.has_macros:
            raise ValueError('Обработчик вернул документ с макросами')
    # Consent text comes from the exported package, not an unrelated transcript.
    from zipfile import ZipFile
    from xml.etree import ElementTree as ET
    with ZipFile(BytesIO(files['document.docx'])) as package:
        texts: list[str] = []
        for name in package.namelist():
            if name.startswith('word/') and name.endswith('.xml'):
                tree = ET.fromstring(package.read(name))
                texts.extend(n.text or '' for n in tree.iter(
                    '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
    text = '\n'.join(texts)
    if len(text.encode()) > 2_000_000:
        raise ValueError('Текст документа превышает лимит предпросмотра')
    return DocumentCandidate(files['document.docx'], tuple(files[n] for n in names),
                             text, profile,
                             tuple(report['changes']), tuple(report['warnings']),
                             report.get('legacy_import') is True, fingerprint)


def runtime_fingerprint() -> str:
    from standard_profiles import runtime_files
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in runtime_files():
        source = root / ('document_runtime/worker.py' if name == 'worker.py' else name)
        digest.update(name.encode()); digest.update(source.read_bytes())
    return digest.hexdigest()


def prepare_document(source: Path, cancel: dict[str, bool] | None = None,
                     timeout: float = 180) -> DocumentCandidate:
    if source.is_symlink() or not source.is_file() or source.suffix.lower() not in {'.doc', '.docx'}:
        raise ValueError('Выберите обычный файл DOC или DOCX. Для PDF этап восстановления структуры ещё не подключён.')
    if not 0 < timeout <= 180:
        raise ValueError('Недопустимое время обработки')
    with source.open('rb') as stream:
        raw = stream.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        raise ValueError('Поддерживаются документы до 32 МБ')
    if source.suffix.lower() == '.docx':
        from document_inspection import inspect_docx
        inspect_docx(source)
    if cancel and cancel.get('cancelled'):
        raise RuntimeError('Обработка документа отменена')
    docker = docker_command()
    expected_runtime = runtime_fingerprint()
    image = subprocess.run([*docker, 'image', 'inspect', IMAGE, '--format', '{{.Id}}'],
                           capture_output=True, text=True, timeout=10)
    image_id = image.stdout.strip()
    if image.returncode or not re.fullmatch(r'sha256:[a-f0-9]{64}', image_id):
        raise RuntimeError('Обработчик документов не подготовлен. Выполните настройку по README; автоматической загрузки и запуска на компьютере не будет.')
    name = 'butuz-document-' + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='butuz-document-input-') as directory:
        staging = Path(directory); staging.chmod(0o755)
        snapshot = staging / ('source' + source.suffix.lower()); snapshot.write_bytes(raw); snapshot.chmod(0o444)
        command = [*docker, 'run', '--name', name, '--pull=never', '--network=none',
                   '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
                   '--user=65534:65534', '--cpus=2', '--memory=1536m', '--memory-swap=1536m',
                   '--pids-limit=128', '--ipc=private', '--ulimit', 'nofile=256:256',
                   '--ulimit', 'fsize=67108864:67108864',
                   '--tmpfs', '/work:rw,noexec,nosuid,nodev,size=256m,mode=1777',
                   '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=96m,mode=1777',
                   '--mount', f'type=bind,src={staging},dst=/input,readonly', image_id]
        worker = BoundedProcess(command, 64_000)
        export: BoundedProcess | None = None
        try:
            worker.wait(timeout, cancel, ready=True)
            # Docker's copy API cannot reliably read tmpfs. A fixed tar command
            # inside the same restricted container streams only the output folder.
            export = BoundedProcess([*docker, 'exec', '--user', '65534:65534', name,
                                     'tar', '-C', '/work/out', '-cf', '-', '.'], MAX_EXPORT)
            export.wait(20, cancel)
            candidate = decode_export(bytes(export.buffers[0]))
            if candidate.runtime_fingerprint != expected_runtime:
                raise RuntimeError('Обработчик документов устарел. Пересоберите butuz-documents:local по README; файл не сохранён.')
            if cancel and cancel.get('cancelled'):
                raise RuntimeError('Обработка документа отменена')
            return candidate
        finally:
            try:
                subprocess.run([*docker, 'rm', '-f', name], capture_output=True, timeout=10)
            finally:
                worker.close()
                if export is not None:
                    export.close()
