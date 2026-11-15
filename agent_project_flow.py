"""Request-owned project sequencing and read-before-edit evidence.

Only tool metadata and typed read artifacts enter this state, never model text.
It complements, rather than replaces, file permissions and GUI approval.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any

from langchain_core.tools import BaseTool
from sandbox_runner import ExecutionResult
from agent_verification import verification_requested


@dataclass(frozen=True)
class ProjectRead:
    path: str
    sha256: str
    start: int
    end: int
    complete: bool


class ProjectFlow:
    def __init__(self, tools: dict[str, BaseTool], task: str = '') -> None:
        metadata = (tools['list_projects'].metadata or {}) if 'list_projects' in tools else {}
        self.root = Path(metadata['project_workspace']) if metadata.get('project_workspace') else None
        self.ids = frozenset(metadata.get('project_ids', []))
        self.reads: dict[str, list[ProjectRead]] = {}
        # Narrow explicit current-user constraints, never inferred from files,
        # history, quoted examples or a generic wish to improve a project.
        text = task.split('\nДоступные копии вложений:', 1)[0]
        text = re.sub(r'```.*?```|«[^»\n]*»|"[^"\n]*"|“[^”\n]*”', '', text, flags=re.S)
        keep_pattern = re.compile(
            r'\b(?:keep|leave|preserve)\b[^.!?\n]{0,120}\btests?\b[^.!?\n]{0,80}\bunchanged\b|'
            r'\b(?:do not|don.t)\s+(?:change|modify|edit)\s+(?:the\s+)?(?:existing\s+)?tests?\b|'
            r'\bне\s+(?:меняй|изменяй|правь|трогай)\s+(?:существующие\s+)?тест|'
            r'\bсохрани\s+[^.!?\n]{0,35}тест[^.!?\n]{0,35}без\s+изменен', re.I)
        pretest_pattern = re.compile(
            r'\b(?:run|execute)\b[^.!?\n]{0,70}\btests?\b[^.!?\n]{0,25}\bbefore\b|'
            r'\b(?:запусти|прогони)\s+[^.!?\n]{0,35}тест[^.!?\n]{0,35}до\s+(?:прав|измен)|'
            r'\bсначала\s+[^.!?\n]{0,30}(?:запусти|прогони)\s+[^.!?\n]{0,25}тест', re.I)
        def positive(pattern: re.Pattern[str]) -> bool:
            return any(not re.search(r'\b(?:do\s+not|don.t|не(?:\s+(?:надо|нужно))?)\s*$',
                                     text[max(0, m.start()-40):m.start()], re.I) for m in pattern.finditer(text))
        self.keep_tests = positive(keep_pattern)
        self.pretest = verification_requested(text) and positive(pretest_pattern)
        self.tested: set[str] = set()

    @property
    def sequential(self) -> bool:
        return self.root is not None and bool(self.ids)

    def key(self, path: Path) -> str | None:
        if self.root is None:
            return None
        try:
            parts = path.relative_to(self.root).parts
        except ValueError:
            return None
        if len(parts) >= 3 and parts[0] in {'attached', 'results'} and parts[1] == 'projects' and parts[2] in self.ids:
            return '/'.join(parts[2:])
        return None

    def observe(self, artifact: object) -> None:
        if (isinstance(artifact, ExecutionResult) and artifact.kind == 'pytest'
                and artifact.exit_code in {0, 1} and artifact.snapshot_hashes):
            key = self.key(Path(artifact.source_root))
            if key:
                self.tested.add(key.split('/')[0])
        if isinstance(artifact, ProjectRead):
            key = self.key(Path(artifact.path))
            if key:
                entries = self.reads.setdefault(key, [])
                # Retain only ranges from this exact version; bound request state.
                self.reads[key] = [r for r in entries if r.sha256 == artifact.sha256][-31:] + [artifact]

    def written(self, path: str) -> None:
        key = self.key(Path(path))
        if key:
            self.reads.pop(key, None)

    def check(self, name: str, args: dict[str, Any]) -> str | None:
        if not self.sequential or self.root is None or 'file_path' not in args:
            return None
        path = (self.root / str(args['file_path'])).resolve()
        key = self.key(path)
        if not key:
            # A bare imported ID is not a workspace-relative file path. Never
            # guess its meaning, choose by basename, or rewrite the arguments.
            try:
                first = path.relative_to(self.root).parts[0]
            except (ValueError, IndexError):
                return None
            if first in self.ids:
                return 'Путь не выполнен: ID проекта не является путём. Скопируй полный путь из project_map; не угадывай его.'
            return None  # General chat files/documents remain supported.
        project_id, *tail = key.split('/')
        if name in {'write_file', 'replace_lines', 'append_to_file'}:
            target = Path(*tail)
            is_test = (any(p in {'test', 'tests'} for p in target.parts)
                       or target.name.startswith('test_') or target.stem.endswith('_test')
                       or '.test.' in target.name or '.spec.' in target.name)
            if self.keep_tests and is_test:
                return ('Правка не выполнена: текущий запрос явно требует сохранить тесты неизменными. '
                        'Читай и запускай существующие тесты, исправляй реализацию; подтверждение записи не запрашивалось.')
            if self.pretest and project_id not in self.tested:
                return ('Правка не выполнена: текущий запрос требует запуска тестов ДО изменений. '
                        'Найди существующий файл/каталог тестов через project_map, вызови run_pytest с точным путём '
                        'и используй фактический результат. При недоступной песочнице сообщи ограничение.')
        base = self.root / 'results/projects' / project_id
        if not base.exists():
            base = self.root / 'attached/projects' / project_id
        current = base.joinpath(*tail)
        if not current.resolve().is_relative_to(self.root.resolve()):
            return 'Путь не выполнен: рабочая копия проекта вышла за пределы чата.'
        if not current.exists():
            if name == 'write_file':  # New files are legitimate, subject to approval.
                return None
            return 'Путь не выполнен: такого файла/каталога в проекте нет. Получи project_map/search_project и используй точный возвращённый путь.'
        if name not in {'write_file', 'replace_lines', 'append_to_file'} or not current.is_file():
            return None
        if current.stat().st_size > 2_000_000:
            return 'Правка не выполнена: файл превышает лимит 2 MB.'
        raw = current.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        reads = [r for r in self.reads.get(key, []) if r.sha256 == digest]
        if name == 'replace_lines':
            start, end = args.get('start_line', 0), args.get('end_line', 0)
        else:
            start, end = 1, len(raw.decode('utf-8').splitlines())
        cursor = start
        for left, right in sorted((r.start, r.end) for r in reads):
            if left <= cursor <= right:
                cursor = right + 1
        if reads and start >= 1 and end >= start and cursor > end:
            return None
        if name != 'replace_lines' and any(r.complete for r in reads):
            return None
        return ('Правка не выполнена: сначала прочитай актуальные строки этого файла через read_file_lines '
                '(для полной перезаписи/добавления прочитай весь файл). Затем выбери правку по полученному содержимому. '
                'Это служебная проверка чтения, а не отказ пользователя; подтверждение ещё не запрашивалось.')
