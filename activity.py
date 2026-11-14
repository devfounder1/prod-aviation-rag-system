"""Request-scoped progress, independent of response text and desktop controls."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Phase = Literal['ready', 'queued', 'thinking', 'searching', 'working', 'approval',
                'answering', 'vision', 'cancelled', 'error']
Route = Literal['CHAT', 'SEARCH', 'AGENT']


@dataclass(frozen=True)
class ActivityEvent:
    phase: Phase
    detail: str = ''
    route: Route | None = None


def tool_activity(name: str) -> ActivityEvent:
    if name == 'search_documents':
        return ActivityEvent('searching', 'Ищу сведения в документах', 'AGENT')
    details = {
        'read_file': 'Читаю файл', 'list_directory': 'Проверяю файлы чата',
        'write_file': 'Готовлю файл', 'append_to_file': 'Дополняю файл',
        'replace_lines': 'Готовлю изменения', 'update_attached_file': 'Готовлю изменение оригинала',
        'read_file_lines': 'Читаю нужные строки', 'find_in_file': 'Ищу внутри файла',
        'get_file_structure': 'Изучаю структуру файла',
        'list_projects': 'Проверяю проекты чата', 'project_map': 'Изучаю карту проекта',
        'search_project': 'Ищу код в проекте', 'run_pytest': 'Запускаю тесты проекта',
        'run_python': 'Запускаю Python',
        'check_python_syntax': 'Проверяю синтаксис Python',
    }
    return ActivityEvent('working', details.get(name, 'Выполняю задачу'), 'AGENT')
