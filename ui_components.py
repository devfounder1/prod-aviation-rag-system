"""Local vector artwork and quiet, native-animated Flet components."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import flet as ft  # type: ignore[import-untyped]

from activity import ActivityEvent, Phase
from assistant_identity import ASSISTANT_NAME

ASSETS = Path(__file__).resolve().parent / 'assets'
ICONS = ASSETS / 'icons' / 'ui'

PALETTE = {
    'bg_main': '#111827', 'bg_sidebar': '#0c1320', 'bg_input': '#1b2638',
    'bg_bubble_user': '#245bcc', 'bg_bubble_ai': '#1b2638',
    'text_primary': '#e6edf7', 'text_secondary': '#9aacc5',
    'accent': '#f6bc60', 'border': '#2d405b',
    'status_ready': '#72dfbb', 'status_busy': '#f6bc60',
}


def brand_icon(name: str, size: int = 24) -> ft.Image:
    if name not in {'chat', 'search', 'agent', 'attach', 'send', 'new_chat', 'delete',
                    'settings', 'files', 'mic', 'stop', 'approval', 'ready', 'image', 'error'}:
        raise ValueError(f'Unknown brand icon: {name}')
    return ft.Image(src=str(ICONS / f'{name}.svg'), width=size, height=size,
                    fit=ft.ImageFit.CONTAIN, exclude_from_semantics=True)


def icon_button(name: str, label: str, on_click: Callable[..., Any],
                primary: bool = False, size: int = 24) -> ft.IconButton:
    artwork = brand_icon(name, size)
    artwork.exclude_from_semantics = False
    artwork.semantics_label = label
    return ft.IconButton(
        content=artwork, tooltip=label, on_click=on_click,
        width=32 if name == 'delete' else 46 if primary else 40,
        height=32 if name == 'delete' else 46 if primary else 40,
        style=ft.ButtonStyle(
            bgcolor='#364055' if primary else {ft.ControlState.HOVERED: '#263a53'},
            shape=ft.RoundedRectangleBorder(radius=12),
            side=ft.BorderSide(0, 'transparent') if name == 'delete' else
                 ft.BorderSide(1, '#9b7645' if primary else '#2d405b'),
        ),
    )


_PHASES: dict[Phase, tuple[str, str, str]] = {
    'ready': ('Готов помочь', 'ready', '#72dfbb'),
    'queued': ('Жду своей очереди', 'chat', '#9edcf2'),
    'thinking': ('Думаю', 'chat', '#9edcf2'),
    'searching': ('Ищу в документах', 'search', '#9edcf2'),
    'working': ('Работаю над задачей', 'agent', '#f6bc60'),
    'approval': ('Жду подтверждения', 'approval', '#f6bc60'),
    'answering': ('Пишу ответ', 'chat', '#9edcf2'),
    'vision': ('Изучаю изображение', 'image', '#9edcf2'),
    'cancelled': ('Остановлено', 'stop', '#9aacc5'),
    'error': ('Не удалось завершить', 'error', '#fca5a5'),
}


class ActivityView:
    def __init__(self) -> None:
        self.event = ActivityEvent('ready')
        self.text = ft.Text(size=12, weight=ft.FontWeight.W_500, max_lines=1)
        self.route = ft.Text(size=10, weight=ft.FontWeight.BOLD, color='#9aacc5')
        self.spinner = ft.ProgressRing(width=12, height=12, stroke_width=1.6,
                                       color='#9edcf2', semantics_label='Запрос выполняется')
        self.symbol = ft.AnimatedSwitcher(brand_icon('ready', 22), duration=180,
                                         transition=ft.AnimatedSwitcherTransition.FADE)
        self.control = ft.Container(
            content=ft.Row([self.symbol, self.text, self.route, self.spinner], spacing=7,
                           tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.symmetric(horizontal=12, vertical=7), border_radius=20,
            animate=ft.Animation(180, ft.AnimationCurve.EASE_OUT),
        )
        self.apply(self.event)

    def apply(self, event: ActivityEvent) -> None:
        label, icon, color = _PHASES[event.phase]
        if event.phase != self.event.phase:
            symbol = brand_icon(icon, 22)
            symbol.key = event.phase
            self.symbol.content = symbol
        self.event = event
        self.text.value = label
        self.text.color = color
        self.route.value = event.route or ''
        self.route.visible = event.route is not None
        self.spinner.visible = event.phase in {'queued', 'thinking', 'searching', 'working', 'answering', 'vision'}
        self.spinner.color = color
        self.control.bgcolor = '#2c261f' if event.phase == 'approval' else '#172438'
        self.control.border = ft.border.all(1, '#82633c' if event.phase == 'approval' else '#2d405b')
        self.control.tooltip = event.detail or label


def welcome_panel(on_example: Callable[[str, str], None]) -> ft.Container:
    def card(mode: str, icon: str, title: str, subtitle: str, example: str) -> ft.ElevatedButton:
        return ft.ElevatedButton(
            content=ft.Column([
                ft.Row([brand_icon(icon, 24), ft.Text(mode, size=11, color='#9aacc5',
                                                    weight=ft.FontWeight.BOLD)], spacing=8),
                ft.Text(title, size=15, weight=ft.FontWeight.W_600, color='#e6edf7'),
                ft.Text(subtitle, size=11, color='#9aacc5', max_lines=2),
            ], spacing=7, tight=True),
            width=210, height=116, on_click=lambda _: on_example(mode, example),
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: '#182438', ft.ControlState.HOVERED: '#223650'},
                padding=16, shape=ft.RoundedRectangleBorder(radius=16),
                side={ft.ControlState.DEFAULT: ft.BorderSide(1, '#2d405b'),
                      ft.ControlState.HOVERED: ft.BorderSide(1, '#6898b7')},
                animation_duration=180,
            ),
        )

    mascot = ft.Container(
        content=ft.Image(src=str(ASSETS / 'avatars' / 'assistant.png'), width=100, height=100,
                         fit=ft.ImageFit.CONTAIN, semantics_label='Маскот BUTUZIK.AI — пёс-пилот'),
        width=120, height=120, padding=10, border_radius=32,
        bgcolor='#1b2c40', border=ft.border.all(1, '#3c586f'),
        shadow=ft.BoxShadow(blur_radius=24, color='#15344b', spread_radius=2),
    )
    return ft.Container(
        content=ft.Column([
            mascot,
            ft.Text(f'Привет, я {ASSISTANT_NAME}', size=27, weight=ft.FontWeight.BOLD,
                    color='#e6edf7', text_align=ft.TextAlign.CENTER),
            ft.Text('Обсудим идею, найдём ответ в документах или создадим файл.', size=13,
                    color='#9aacc5', text_align=ft.TextAlign.CENTER),
            ft.Container(height=3),
            ft.Row([
                card('CHAT', 'chat', 'Давайте поговорим', 'Объяснения, идеи и вопросы',
                     'Расскажи, чем ты можешь мне помочь'),
                card('SEARCH', 'search', 'Найдём в документах', 'Ответ с проверяемыми источниками',
                     'Что такое сигнал PPS?'),
                card('AGENT', 'agent', 'Сделаем вместе', 'Документы, анализ и готовые файлы',
                     'Создай файл welcome.txt с текстом «Привет от BUTUZIK.AI!»'),
            ], wrap=True, spacing=10, run_spacing=10, alignment=ft.MainAxisAlignment.CENTER),
            ft.Text('Выберите пример или напишите свой запрос ниже', size=11, color='#9aacc5',
                    text_align=ft.TextAlign.CENTER),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER,
            spacing=13, scroll=ft.ScrollMode.AUTO),
        padding=ft.padding.symmetric(horizontal=20, vertical=10),
        expand=True, alignment=ft.alignment.center,
    )
