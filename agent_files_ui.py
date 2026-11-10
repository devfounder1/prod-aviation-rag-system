"""Desktop file approvals and discoverable per-chat agent output."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
import os
import platform
import subprocess
import tempfile
import threading
from typing import Any

import flet as ft  # type: ignore[import-untyped]

from file_tools import output_files, workspace_for_chat
from jobs import RequestJob
from ui_components import brand_icon


class FileApproval:
    """Worker waits; only the page event loop opens/closes the modal."""

    def __init__(self, page: ft.Page, job: RequestJob,
                 is_current: Callable[[], bool]) -> None:
        self.page = page
        self.job = job
        self.is_current = is_current
        self.done = threading.Event()
        self.lock = threading.Lock()
        self.approved = False
        self.dialog: ft.AlertDialog | None = None

    def decide(self, approved: bool) -> None:
        with self.lock:
            if self.done.is_set():
                return
            self.approved = approved and self.is_current() and not self.job.token.get('cancelled')
            self.done.set()
        self.page.run_task(self.close)

    async def close(self) -> None:
        if self.dialog is not None:
            self.page.close(self.dialog)

    async def show(self, description: str) -> None:
        if self.done.is_set() or not self.is_current() or self.job.token.get('cancelled'):
            self.decide(False)
            return
        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row([brand_icon('approval', 28), ft.Text('Подтвердить действие агента')], spacing=10),
            content=ft.Container(
                width=700,
                content=ft.Column([
                    ft.Text('Проверьте действие, путь и содержимое. Разрешение действует только на эту запись.'),
                    ft.Container(
                        content=ft.Column([
                            ft.Text(description, selectable=True, font_family='monospace', size=13),
                        ], scroll=ft.ScrollMode.AUTO, height=330),
                        bgcolor='#1e293b', padding=12, border_radius=8,
                    ),
                ], tight=True),
            ),
            actions=[
                ft.TextButton('Отмена', on_click=lambda _: self.decide(False)),
                ft.ElevatedButton('Разрешить запись', on_click=lambda _: self.decide(True)),
            ],
            on_dismiss=lambda _: self.decide(False),
        )
        self.page.open(self.dialog)
        # Cancellation can race with UI construction.
        if self.done.is_set():
            await self.close()

    def wait(self, description: str, timeout: float = 120) -> bool:
        self.job.token.on_cancel(lambda: self.decide(False))
        self.page.run_task(self.show, description)
        if not self.done.wait(timeout):
            self.decide(False)
        return self.approved and not self.job.token.get('cancelled') and self.is_current()


def reveal_path(path: Path) -> None:
    """Reveal a file or open a folder using the desktop, never a shell command."""
    if platform.system() == 'Darwin':
        subprocess.run(['open', *(['-R'] if path.is_file() else []), str(path)], check=True)
    elif platform.system() == 'Windows':
        subprocess.run(['explorer', *(['/select,', str(path)] if path.is_file() else [str(path)])], check=False)
    else:
        subprocess.run(['xdg-open', str(path.parent if path.is_file() else path)], check=True)


def export_copy(chat_id: str, source: Path, destination: Path) -> None:
    """Export only a current chat output; preserve bytes and leave the source intact."""
    source = source.resolve(strict=True)
    if source not in [path.resolve() for path in output_files(chat_id)]:
        raise ValueError('Этот файл не принадлежит результатам текущего чата')
    destination = destination.expanduser().absolute()
    if destination.is_symlink():
        raise ValueError('Выберите обычный файл, а не символическую ссылку')
    if destination.resolve() == source:
        return
    # Export cannot overwrite another chat's files or internal app data.
    project = Path(__file__).resolve().parent
    if destination.resolve().is_relative_to(project):
        raise ValueError('Выберите папку вне приложения, например «Документы» или «Рабочий стол»')
    raw = source.read_bytes()
    fd, temp = tempfile.mkstemp(prefix='.butuz-export-', dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, destination)
    finally:
        Path(temp).unlink(missing_ok=True)


class AgentFilesUI:
    def __init__(self, page: ft.Page, current_chat: Callable[[], str | None],
                 notify: Callable[[str], None]) -> None:
        self.page = page
        self.current_chat = current_chat
        self.notify = notify
        self.pending_export: tuple[str, Path] | None = None
        self.picker = ft.FilePicker(on_result=self.save_result)
        page.overlay.append(self.picker)

    def open(self, _: Any = None) -> None:
        chat_id = self.current_chat()
        if not chat_id:
            self.notify('Сначала создайте чат')
            return
        self.page.run_task(self.show, chat_id)

    async def show(self, chat_id: str) -> None:
        try:
            root, paths = await asyncio.to_thread(
                lambda: (workspace_for_chat(chat_id), output_files(chat_id)))
        except Exception as exc:
            self.notify(f'Не удалось прочитать файлы: {exc}')
            return
        if self.current_chat() != chat_id:
            return
        rows: list[ft.Control] = []
        dialog: ft.AlertDialog
        for path in paths:
            rows.append(ft.Row([
                brand_icon('files'),
                ft.Text(str(path.relative_to(root)), expand=True, selectable=True),
                ft.IconButton(ft.Icons.FOLDER_OPEN, tooltip='Показать в папке',
                              on_click=lambda _, p=path: self.reveal(chat_id, p)),
                ft.TextButton('Сохранить как…',
                              on_click=lambda _, p=path: self.save_as(chat_id, p, dialog)),
            ]))
        dialog = ft.AlertDialog(
            title=ft.Text('Файлы чата'),
            content=ft.Container(width=720, content=ft.Column([
                ft.Text('Здесь результаты работы агента. Копии прикреплённых документов скрыты.'),
                ft.Text(str(root), selectable=True, size=12),
                ft.Column(rows or [ft.Text('В этом чате ещё нет созданных файлов.')],
                          height=300, scroll=ft.ScrollMode.AUTO),
            ], tight=True)),
            actions=[
                ft.TextButton('Открыть папку', on_click=lambda _: self.reveal(chat_id, root)),
                ft.TextButton('Закрыть', on_click=lambda _: self.page.close(dialog)),
            ],
        )
        self.page.open(dialog)

    def reveal(self, chat_id: str, path: Path) -> None:
        if self.current_chat() != chat_id:
            return
        try:
            root = workspace_for_chat(chat_id).resolve()
            if path.resolve() != root and path not in output_files(chat_id):
                raise ValueError('Файл недоступен')
            reveal_path(path)
        except Exception as exc:
            self.notify(f'Не удалось открыть папку: {exc}')

    def save_as(self, chat_id: str, path: Path, dialog: ft.AlertDialog) -> None:
        if self.current_chat() != chat_id or self.pending_export:
            return
        self.pending_export = (chat_id, path)
        self.page.close(dialog)
        documents = Path.home() / 'Documents'
        try:
            self.picker.save_file(dialog_title='Сохранить результат агента', file_name=path.name,
                                  initial_directory=str(documents if documents.exists() else Path.home()))
        except Exception as exc:
            self.pending_export = None
            self.notify(f'Не удалось открыть сохранение: {exc}')

    def save_result(self, event: ft.FilePickerResultEvent) -> None:
        pending, self.pending_export = self.pending_export, None
        if not pending or not event.path:
            return
        chat_id, source = pending
        if self.current_chat() != chat_id:
            return
        try:
            destination = Path(event.path)
            export_copy(chat_id, source, destination)
            self.notify(f'Сохранено: {destination}')
        except Exception as exc:
            self.notify(f'Не удалось сохранить файл: {exc}')
