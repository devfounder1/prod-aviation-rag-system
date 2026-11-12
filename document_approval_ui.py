"""Native page preview and exact-candidate approval, owned by the current job."""
from __future__ import annotations

import base64
from collections.abc import Callable

import flet as ft  # type: ignore[import-untyped]

from agent_files_ui import FileApproval
from document_jobs import DocumentProposal
from jobs import RequestJob
from ui_dispatch import UiDispatcher


class DocumentApproval(FileApproval):
    def __init__(self, page: ft.Page, job: RequestJob, is_current: Callable[[], bool],
                 proposal: DocumentProposal, ui: UiDispatcher | None = None) -> None:
        super().__init__(page, job, is_current, ui)
        self.proposal = proposal

    async def show(self, description: str) -> None:
        if self.done.is_set() or not self.is_current() or self.job.token.get('cancelled'):
            self.decide(False)
            return
        candidate = self.proposal.candidate
        current = [0]
        image = ft.Image(src_base64=base64.b64encode(candidate.pages[0]).decode(),
                         width=680, fit=ft.ImageFit.CONTAIN)
        label = ft.Text(f'Страница 1 из {len(candidate.pages)}')

        def move(delta: int) -> None:
            if self.done.is_set():
                return
            current[0] = max(0, min(len(candidate.pages)-1, current[0]+delta))
            image.src_base64 = base64.b64encode(candidate.pages[current[0]]).decode()
            label.value = f'Страница {current[0]+1} из {len(candidate.pages)}'
            self.page.update()

        checked = ft.Checkbox(label='Я проверил страницы и замечания; сохранить этот проект DOCX')
        save = ft.ElevatedButton('Сохранить DOCX', disabled=True,
                                on_click=lambda _: self.decide(bool(checked.value)))
        def acknowledge(event: ft.ControlEvent) -> None:
            save.disabled = not event.control.value
            self.page.update()

        checked.on_change = acknowledge
        tabs = ft.Tabs(tabs=[
            ft.Tab(text='Страницы', content=ft.Column([
                ft.Row([ft.TextButton('Назад', on_click=lambda _: move(-1)), label,
                        ft.TextButton('Далее', on_click=lambda _: move(1))]),
                ft.Column([image], height=380, scroll=ft.ScrollMode.AUTO),
            ])),
            ft.Tab(text='Текст', content=ft.Column([
                ft.Text(candidate.text, selectable=True, size=12),
            ], height=420, scroll=ft.ScrollMode.AUTO)),
            ft.Tab(text='Проверки', content=ft.Column([
                ft.Text(self.proposal.description(), selectable=True, size=13),
            ], height=420, scroll=ft.ScrollMode.AUTO)),
        ], height=470)
        self.dialog = ft.AlertDialog(
            modal=True, title=ft.Text('Проверить оформление перед сохранением'),
            content=ft.Container(width=740, content=ft.Column([
                ft.Text('Оригинал сохранён. Проверьте штампы, таблицы, содержание и предупреждения. '
                        'Базовый профиль не подтверждает полное соответствие всем требованиям ГОСТ.', size=13),
                tabs, checked,
            ], tight=True)),
            actions=[ft.TextButton('Отмена', on_click=lambda _: self.decide(False)), save],
            on_dismiss=lambda _: self.decide(False),
        )
        self.page.open(self.dialog)
        if self.done.is_set():
            await self.close()
