"""Disposable local Docker execution. Never falls back to host execution."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from typing import BinaryIO

IMAGE = 'butuz-sandbox:local'
LIMIT = 64_000
BOOT = '''import os, shutil, subprocess, sys
for name in os.listdir('/input'):
    src, dst = '/input/' + name, '/work/' + name
    if os.path.isdir(src): shutil.copytree(src, dst)
    else: shutil.copyfile(src, dst)
os.chdir('/work')
os.environ.update(HOME='/tmp',PYTHONDONTWRITEBYTECODE='1')
raise SystemExit(subprocess.run(sys.argv[1:], timeout=30).returncode)
'''


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    seconds: float

    def render(self) -> str:
        return (f'Песочница: {self.status}; код завершения: {self.exit_code}; '
                f'время: {self.seconds:.2f} с\nstdout:\n{self.stdout}\nstderr:\n{self.stderr}')


def docker_command() -> list[str]:
    binary = shutil.which('docker')
    sockets = [Path.home() / '.docker/run/docker.sock', Path('/var/run/docker.sock')]
    endpoint = next((p for p in sockets if p.is_socket()), None)
    if not binary or endpoint is None:
        raise RuntimeError('Локальный Docker недоступен. Запустите Docker Desktop; выполнения на хосте не будет.')
    return [binary, '--host', f'unix://{endpoint}']


def snapshot(root: Path, destination: Path) -> None:
    total = 0
    for source in root.rglob('*'):
        relative = source.relative_to(root)
        if any(part.startswith('.') or part == '__pycache__' for part in relative.parts):
            continue
        if source.is_symlink() or not source.is_file():
            continue
        if not source.resolve().is_relative_to(root.resolve()):
            continue
        if source.suffix.lower() not in {'.py', '.txt', '.csv', '.json', '.toml', '.ini', '.cfg', '.yaml', '.yml'}:
            continue
        raw = source.read_bytes()
        total += len(raw)
        if len(raw) > 2_000_000 or total > 20_000_000:
            raise ValueError('Файлы песочницы превышают лимит 20 МБ (2 МБ на файл)')
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)


def execute(root: Path, file_path: str, tests: bool = False,
            cancel: dict[str, bool] | None = None, timeout: float = 30) -> ExecutionResult:
    started = time.monotonic()
    if not 0 < timeout <= 30:
        raise ValueError('Timeout must be between 0 and 30 seconds')
    root = root.resolve()
    target = (root / file_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError('Выберите путь внутри рабочей папки чата')
    from project_workspace import effective_path, project_location
    target = effective_path(root, target)
    location = project_location(root, target)
    if location:
        project_id, _ = location
        kind = target.relative_to(root).parts[0]
        root = root / kind / 'projects' / project_id
    if not ((target.is_file() and target.suffix == '.py') or (tests and target.is_dir())):
        raise ValueError('Выберите Python-файл или, для pytest, папку тестов внутри проекта')
    relative = target.relative_to(root)
    if any(part.startswith('.') for part in relative.parts):
        raise ValueError('Скрытые файлы не передаются в песочницу')
    docker = docker_command()
    env = {key: value for key, value in os.environ.items()
           if key in {'PATH', 'HOME', 'TMPDIR', 'SYSTEMROOT'}}
    inspected = subprocess.run([*docker, 'image', 'inspect', IMAGE, '--format', '{{.Id}}'],
                               capture_output=True, text=True, timeout=10, env=env)
    image_id = inspected.stdout.strip()
    if inspected.returncode or not re.fullmatch(r'sha256:[a-f0-9]{64}', image_id):
        raise RuntimeError('Образ песочницы не установлен. Выполните docker build -t butuz-sandbox:local sandbox. '
                           'Во время работы образы и зависимости не скачиваются.')
    name = 'butuz-run-' + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='butuz-sandbox-') as directory:
        source = Path(directory)
        source.chmod(0o755)
        snapshot(root, source)
        if not (source / relative).exists():
            raise ValueError('Выбранный файл не попал в безопасную копию')
        # The only mount is an immutable snapshot. Container writes disappear with /work.
        command = [*docker, 'run', '--name', name, '--rm', '--pull=never', '--network=none',
                   '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
                   '--user=65534:65534', '--cpus=1', '--memory=512m', '--memory-swap=512m',
                   '--pids-limit=64', '--ipc=private', '--ulimit', 'nofile=128:128',
                   '--tmpfs', '/work:rw,nosuid,nodev,size=64m,mode=1777',
                   '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777',
                   '--mount', f'type=bind,src={source},dst=/input,readonly',
                   '--workdir=/work', '--entrypoint=python', image_id, '-I', '-c', BOOT,
                   'python', *(['-m', 'pytest', '-q', '-p', 'no:cacheprovider'] if tests else ['-u']), './' + str(relative)]
        if cancel and cancel.get('cancelled'):
            return ExecutionResult('отменено', None, '', '', time.monotonic() - started)
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        buffers: list[bytearray] = [bytearray(), bytearray()]
        overflow = threading.Event()
        lock = threading.Lock()
        def read(pipe: BinaryIO | None, index: int) -> None:
            assert pipe is not None
            while chunk := pipe.read(4096):
                with lock:
                    available = LIMIT - sum(len(buffer) for buffer in buffers)
                    buffers[index].extend(chunk[:max(available, 0)])
                    if len(chunk) > available:
                        overflow.set()
        threads = [threading.Thread(target=read, args=(pipe, index), daemon=True)
                   for index, pipe in enumerate((process.stdout, process.stderr))]
        for thread in threads:
            thread.start()
        status = 'завершено'
        try:
            while process.poll() is None:
                if cancel and cancel.get('cancelled'):
                    status = 'отменено'
                    break
                if overflow.is_set():
                    status = 'превышен лимит вывода'
                    break
                if time.monotonic() - started >= timeout:
                    status = 'превышено время выполнения'
                    break
                time.sleep(0.05)
        finally:
            # rm -f also stops detached children inside the container's PID namespace.
            try:
                subprocess.run([*docker, 'rm', '-f', name], capture_output=True, timeout=10, env=env)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
            for thread in threads:
                thread.join(2)
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()
        if overflow.is_set() and status == 'завершено':
            status = 'превышен лимит вывода'
        if status == 'завершено' and process.returncode != 0:
            status = 'ошибка выполнения'
        return ExecutionResult(status, process.returncode, buffers[0].decode('utf-8', 'replace'),
                               buffers[1].decode('utf-8', 'replace'), time.monotonic() - started)
