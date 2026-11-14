"""Visible in-app folder selection, independent of native FilePicker plugins."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import os
from pathlib import Path
from typing import Any

import flet as ft  # type: ignore[import-untyped]

from ui_dispatch import UiDispatcher


def folder_entries(value: str) -> tuple[Path, list[Path], bool]:
    if not value.strip() or not Path(value).expanduser().is_absolute():
        raise ValueError('Укажите полный путь к папке')
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError('Укажите папку, а не файл')
    directories = []
    truncated = False
    with os.scandir(path) as entries:
        for index, entry in enumerate(entries):
            if index >= 10000:
                truncated = True
                break
            if not entry.name.startswith('.') and entry.is_dir(follow_symlinks=False):
                directories.append(Path(entry.path))
    directories.sort(key=lambda p: p.name.casefold())
    return path, directories[:200], truncated or len(directories) > 200


class ProjectFolderBrowser:
    def __init__(self, page: Any, current_chat: Callable[[], str | None],
                 choose: Callable[[str, Path], None], ui: UiDispatcher) -> None:
        self.page = page
        self.current_chat = current_chat
        self.on_choose = choose
        self.ui = ui
        self.session: object | None = None
        self.dialog: ft.AlertDialog | None = None

    def open(self) -> None:
        chat_id = self.current_chat()
        if not chat_id or not self.ui.active or self.session is not None:
            return
        session = self.session = object()
        if not self.ui.run_task(self.show, chat_id, session):
            self.session = None

    def cancel(self) -> None:
        self.session = None
        dialog, self.dialog = self.dialog, None
        if dialog is not None:
            self.ui.run_task(self.close_dialog, dialog)

    async def close_dialog(self, dialog: ft.AlertDialog) -> None:
        self.page.close(dialog)

    async def show(self, chat_id: str, session: object) -> None:
        def valid() -> bool:
            return self.session is session and self.current_chat() == chat_id and self.ui.active

        if not valid():
            if self.session is session:
                self.session = None
            return
        path_field = ft.TextField(label='Путь к папке проекта', value=str(Path.home()),
                                  expand=True, text_size=13, autofocus=True)
        status = ft.Text('Читаю список папок…', size=12)
        rows = ft.Column([], spacing=2, scroll=ft.ScrollMode.AUTO, height=280)
        revision = 0
        dialog: ft.AlertDialog

        async def navigate(_: Any = None) -> None:
            nonlocal revision
            if not valid():
                return
            revision += 1
            mine = revision
            value = path_field.value or ''
            status.value = 'Читаю список папок…'
            self.page.update()
            try:
                path, directories, truncated = await asyncio.to_thread(folder_entries, value)
            except Exception as exc:
                if valid() and mine == revision:
                    status.value = f'Не удалось открыть папку: {exc}'
                    rows.controls.clear()
                    self.page.update()
                return
            if not valid() or mine != revision:
                return
            # Do not replace a path the user edited while the listing was loading.
            if path_field.value != value:
                return
            path_field.value = str(path)
            rows.controls.clear()
            for directory in directories:
                async def enter(_: Any, selected: Path = directory) -> None:
                    if valid():
                        path_field.value = str(selected)
                        await navigate()
                rows.controls.append(ft.TextButton(directory.name, icon=ft.Icons.FOLDER_OUTLINED,
                                                    on_click=enter))
            status.value = ('Показаны первые папки. Уточните путь в поле.' if truncated else
                            'Выберите вложенную папку или импортируйте текущую.')
            if not directories:
                rows.controls.append(ft.Text('Вложенных папок нет.'))
            self.page.update()

        async def up(_: Any) -> None:
            if valid():
                path_field.value = str(Path(path_field.value or '').expanduser().parent)
                await navigate()

        async def confirm(_: Any) -> None:
            if not valid():
                return
            value = path_field.value or ''
            try:
                path, _, _ = await asyncio.to_thread(folder_entries, value)
            except Exception as exc:
                if valid():
                    status.value = f'Папка не выбрана: {exc}'
                    self.page.update()
                return
            if not valid() or path_field.value != value:
                return
            self.session = None
            self.dialog = None
            self.page.close(dialog)
            self.on_choose(chat_id, path)

        def dismiss(_: Any = None) -> None:
            if self.session is session:
                self.cancel()

        path_field.on_submit = navigate
        dialog = ft.AlertDialog(
            modal=True, title=ft.Text('Открыть папку проекта'),
            content=ft.Container(width=680, content=ft.Column([
                ft.Text('Выберите папку или вставьте полный путь. В чат будет скопирован исходный код; '
                        'выбранная папка останется без изменений.'),
                ft.Row([ft.IconButton(ft.Icons.ARROW_UPWARD, tooltip='На папку выше', on_click=up), path_field]),
                ft.TextButton('Показать папки', on_click=navigate), status, rows,
            ], tight=True)),
            actions=[ft.TextButton('Отмена', on_click=dismiss),
                     ft.FilledButton('Импортировать проект', on_click=confirm)],
            on_dismiss=dismiss,
        )
        self.dialog = dialog
        self.page.open(dialog)  # Show feedback before doing any filesystem work.
        await navigate()
