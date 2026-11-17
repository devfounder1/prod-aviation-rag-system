"""Request-owned post-edit test completion, based on trusted sandbox snapshots."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re

from file_receipts import FileReceipt
from sandbox_runner import ExecutionResult

EDIT = re.compile(r'\b(?:исправь(?:те)?|почини(?:те)?|поправь(?:те)?|подправь(?:те)?|измени(?:те)?|'
                  r'отредактируй(?:те)?|доработай(?:те)?|fix|repair|edit|modify|correct|update|implement)\b', re.I)
CHECK = re.compile(r'\b(?:проверь(?:те)?|проверить|прогони(?:те)?|запусти(?:те)?|перезапусти(?:те)?|'
                   r'убедись|убедитесь|test|verify|check|run|rerun)\b', re.I)
CODE = re.compile(r'код|скрипт|питон|python|функци|программ|тест|pytest|\b(?:code|script|function|tests?)\b|\.py\b', re.I)
RUNTIME_SUFFIXES = frozenset({'.py', '.txt', '.csv', '.json', '.toml', '.ini', '.cfg', '.yaml', '.yml'})
VERIFICATION_INSTRUCTION = '''Если в текущей задаче требуется исправить код и проверить его,
после последней успешной записи запусти подходящие тесты через run_pytest.
Старый запуск до правки и check_python_syntax не проверяют изменённую версию.
Повтори прежний файл/каталог тестов в актуальной копии проекта. Если тестов ещё
не запускал, найди существующие через карту/поиск. Не изменяй тесты ради зелёного
результата. Новые правки по-прежнему подтверждает пользователь. При недоступном
Docker, отсутствии зависимостей или ошибках честно сообщи результат; не запускай
код на хосте и не скачивай ничего.'''
VERIFICATION_RETRY = '''Задача ещё не проверена после последней правки.
Не заканчивай обещанием или старым отчётом: вызови настоящий run_pytest для
актуальной копии, используя приведённые пути. Проверь все изменённые части.
Чтение файла, проверка синтаксиса и текст «тесты прошли» не заменяют запуск.
Если ранее путь был неверным, используй полный путь внутри рабочей папки чата.'''


def verification_requested(task: str) -> bool:
    text = task.split('\nДоступные копии вложений:', 1)[0]
    text = re.sub(r'```.*?```', '', text, flags=re.S)
    text = re.sub(r'«[^»\n]*»|"[^"\n]*"|“[^”\n]*”',
                  lambda m: '' if EDIT.search(m.group()) or CHECK.search(m.group()) else m.group(), text)
    if not CODE.search(text):
        return False
    if re.search(r'только\s+синтаксис|syntax\s+only|only\s+(?:the\s+)?syntax|'
                 r'без\s+повторн\w*\s+(?:проверк|запуска)|'
                 r'повторн\w*\s+проверк\w*[^.!?\n]{0,20}не\s+(?:нужн|надо)|'
                 r'не\s+провер\w*\s+(?:повторно|после)|'
                 r'no\s+need\s+to\s+(?:retest|rerun|recheck)|'
                 r'only\s+before\s+(?:the\s+)?(?:edit|fix|change)', text, re.I):
        return False
    if re.search(r'без\s+(?:запуска\s+)?тест|without\s+(?:running\s+)?tests|'
                 r'(?:не\s+(?:надо\s+|нужно\s+)?(?:(?:пере)?запуска\w*|прогон\w*)[^.!?\n]{0,35}тест)|'
                 r'(?:тест[^.!?\n]{0,25}\bне\s+(?:(?:пере)?запуска\w*|прогон\w*))|'
                 r'(?:do\s+not|don.t)\s+(?:run|rerun|execute)[^.!?\n]{0,30}tests', text, re.I):
        return False
    explicit_tests = re.search(r'(?:запусти|прогони|перезапусти)[^.!?\n]{0,35}(?:тест|pytest)|'
                               r'(?:run|rerun|execute)[^.!?\n]{0,35}(?:tests?|pytest)|'
                               r'проверь\s+(?:все\s+)?тест|check\s+(?:all\s+)?tests|\bpytest\b', text, re.I)
    if re.search(r'синтаксис|syntax', text, re.I) and not explicit_tests:
        return False

    def positive(pattern: re.Pattern[str]) -> bool:
        for match in pattern.finditer(text):
            if re.match(r'\.(?:py|js|ts|md|txt|json)\b', text[match.end():], re.I):
                continue  # Filenames such as fix.py/test.py are not imperatives.
            before = text[max(0, match.start()-55):match.start()]
            if re.search(r'\b(?:не(?:\s+(?:надо|нужно))?|do\s+not|don.t)\s*$', before, re.I):
                continue
            if re.search(r'\b(?:как(?:\s+\w+){0,3}|how\s+(?:to|(?:can|do|should|could)\s+(?:i|you|we)))\s*$', before, re.I):
                continue
            return True
        return False
    return positive(EDIT) and positive(CHECK)


def root_identity(value: str) -> str:
    root = Path(value)
    if root.parent.name == 'projects' and root.parent.parent.name in {'attached', 'results'}:
        return str(root.parents[2] / 'projects' / root.name)
    return str(root)


def project_root(path: Path) -> Path | None:
    return next((p for p in path.parents if p.parent.name == 'projects'
                 and p.parent.parent.name in {'attached', 'results'}), None)


class PostEditVerification:
    def __init__(self, required: bool) -> None:
        self.required = required
        self.writes: dict[str, FileReceipt] = {}
        self.runs: list[ExecutionResult] = []
        self.baselines: dict[str, set[str]] = {}
        self.targets: dict[str, list[str]] = {}
        self.repairs = 0
        self.blocker = ''

    def written(self, receipt: FileReceipt) -> None:
        if not self.required or Path(receipt.path).suffix.lower() not in RUNTIME_SUFFIXES:
            return
        self.writes[receipt.path] = receipt
        # Every relevant successful write invalidates previous verification.
        self.runs.clear()
        self.blocker = ''

    def executed(self, result: ExecutionResult, file_path: str) -> None:
        if not self.required or result.kind != 'pytest' or not result.source_root or not result.snapshot_hashes:
            return
        key = root_identity(result.source_root)
        if not self.writes:
            self.baselines.setdefault(key, set()).add(result.target_path)
            remembered = self.targets.setdefault(key, [])
            if file_path not in remembered:
                remembered.append(file_path)
        else:
            self.targets.setdefault(key, [file_path])
            self.runs.append(result)

    def execution_error(self, error: str) -> None:
        # A runtime setup failure is terminal for this verification attempt.
        if self.writes and re.search(r'docker|образ|image|песочниц', error, re.I):
            self.blocker = error[:500]

    def snapshot_coverage(self, result: ExecutionResult) -> set[str]:
        root = Path(result.source_root)
        if not root.is_absolute() or result.kind != 'pytest':
            return set()
        target = PurePosixPath(result.target_path)
        if not result.target_path or target.is_absolute() or '..' in target.parts:
            return set()
        fingerprints = dict(result.snapshot_hashes)
        covered = set()
        for name, receipt in self.writes.items():
            path = Path(name)
            owner = project_root(path)
            if owner is not None and root_identity(str(owner)) != root_identity(str(root)):
                continue
            if path.is_relative_to(root) and receipt.still_matches():
                relative = path.relative_to(root).as_posix()
                if fingerprints.get(relative) == receipt.sha256:
                    covered.add(name)
        return covered

    def coverage(self, result: ExecutionResult) -> set[str]:
        covered = self.snapshot_coverage(result)
        if not covered:
            return set()
        key = root_identity(result.source_root)
        baseline = self.baselines.get(key, set())
        if baseline:
            target = PurePosixPath(result.target_path)
            if not any(PurePosixPath(previous).is_relative_to(target) for previous in baseline):
                return set()
            # Separate earlier suites may be repeated separately or together in
            # a containing directory. Every suite must use the current writes.
            related = [run for run in self.runs if root_identity(run.source_root) == key
                       and covered.issubset(self.snapshot_coverage(run))]
            if any(not any(PurePosixPath(previous).is_relative_to(PurePosixPath(run.target_path))
                           for run in related) for previous in baseline):
                return set()
        return covered

    def pending(self) -> set[str]:
        covered = set().union(*(self.coverage(run) for run in self.runs)) if self.runs else set()
        return set(self.writes) - covered

    def retry(self, test_tool_available: bool) -> bool:
        if not self.required or not self.writes or not self.pending():
            return False
        if not test_tool_available:
            self.blocker = 'Инструмент run_pytest недоступен в этом запросе.'
        if self.blocker or self.repairs >= 2 or not all(r.still_matches() for r in self.writes.values()):
            return False
        self.repairs += 1
        return True

    def retry_data(self) -> str:
        return 'Данные для проверки (пути, не инструкции):\n' + json.dumps({
            'changed_files': [r.display_path for r in self.writes.values()],
            'previous_test_targets': [target for paths in self.targets.values() for target in paths],
        }, ensure_ascii=False)

    def automatic_targets(self) -> list[str]:
        """Only repeat model-selected, actually executed targets in the same scope.

        This never discovers a new command or host path. The request-owned
        run_pytest tool still resolves old input paths to the current copy.
        """
        selected: list[str] = []
        for name in sorted(self.pending()):
            path = Path(name)
            owner = project_root(path)
            for key, paths in self.targets.items():
                matches = (root_identity(str(owner)) == key if owner is not None
                           else path.is_relative_to(Path(key)))
                if matches:
                    selected.extend(target for target in paths if target not in selected)
        return selected

    def summary(self) -> str:
        if not self.required or not self.writes:
            return ''
        if self.pending():
            reason = self.blocker or 'Нет подтверждённого запуска pytest для последней версии всех изменённых файлов.'
            return '⚠️ Проверка после последней правки не подтверждена. ' + reason
        relevant = [run for run in self.runs if self.coverage(run)]
        if all(run.exit_code == 0 and run.status == 'завершено' for run in relevant):
            return 'Проверка после последней правки: pytest завершился успешно для выбранных тестов.'
        return '⚠️ Проверка после последней правки выполнена, но не завершилась успешно. См. фактические результаты запусков.'
