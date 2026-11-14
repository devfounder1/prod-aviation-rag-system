"""Project intake/navigation/editing use snapshots, never source-folder execution."""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

import file_tools
import project_workspace as pw
from agent_context import AgentContext, ContextBudgetError, message_size
from ai_agent import LocalAgent
from file_receipts import FileReceipt
from jobs import CancelToken
from sandbox_runner import ExecutionResult, execute


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, pw.ProjectInfo]:
    monkeypatch.setattr(file_tools, 'WORKSPACE', tmp_path / 'chats')
    source = tmp_path / 'demo'
    (source / 'package').mkdir(parents=True)
    (source / 'tests').mkdir()
    (source / 'package' / '__init__.py').write_text('')
    (source / 'package' / 'calc.py').write_text('import math\n\ndef add(a, b):\n    return a - b\n')
    (source / 'tests' / 'test_calc.py').write_text('from package.calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n')
    (source / 'pyproject.toml').write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    root = file_tools.workspace_for_chat('a')
    return source, root, pw.import_project(root, source)


def test_import_filters_files_preserves_tree_and_records_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_tools, 'WORKSPACE', tmp_path / 'chats')
    source = tmp_path / 'source'; source.mkdir()
    keep = source / 'src' / 'app.py'; keep.parent.mkdir(); keep.write_text('def greet(): pass\n')
    for folder in ['node_modules', '.git', '.venv', '__pycache__', 'dist', 'build']:
        (source / folder).mkdir(); (source / folder / 'private.py').write_text('secret')
    for name in ['.env', 'credentials.json', 'photo.png', 'bundle.min.js', 'uv.lock']:
        (source / name).write_text('excluded')
    (source / 'binary.txt').write_bytes(b'\0binary')
    (source / 'latin.txt').write_bytes(b'\xff')
    (source / 'link.py').symlink_to(keep)
    (source / 'alias').symlink_to(keep.parent, target_is_directory=True)
    os.mkfifo(source / 'fifo.py')
    before = keep.read_bytes()
    root = file_tools.workspace_for_chat('a')
    info = pw.import_project(root, source)
    assert info.files == 1 and info.skipped >= 10
    assert (root / info.input_path / 'src/app.py').read_bytes() == before
    assert not (root / info.result_path).exists()
    assert file_tools.output_files('a') == []
    assert pw.projects(root) == [info]
    assert pw.manifest(root, info.id)['hashes']['src/app.py'] == hashlib.sha256(before).hexdigest()
    assert pw.import_project(root, source).id != info.id  # Explicit reimport never overwrites old data.


def test_limits_and_cancellation_never_publish_partial_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / 'source'; source.mkdir()
    (source / 'a.py').write_text('a=1'); (source / 'b.py').write_text('b=1')
    root = tmp_path / 'chat'; root.mkdir()
    monkeypatch.setattr(pw, 'MAX_FILES', 1)
    with pytest.raises(ValueError, match='лимит'):
        pw.import_project(root, source)
    assert pw.projects(root) == [] and not list((root / 'attached/projects').iterdir())
    monkeypatch.setattr(pw, 'MAX_FILES', 1500)
    token = CancelToken()
    original = pw.safe_file
    def cancel_during_copy(path: Path, base: Path) -> bytes:
        raw = original(path, base); token['cancelled'] = True; return raw
    monkeypatch.setattr(pw, 'safe_file', cancel_during_copy)
    with pytest.raises(RuntimeError, match='отмен'):
        pw.import_project(root, source, token)
    assert not list((root / 'attached/projects').iterdir()) and pw.projects(root) == []
    assert not list(root.glob('.import-*'))


def test_map_search_are_scoped_paginated_and_do_not_execute(project: tuple[Path, Path, pw.ProjectInfo]) -> None:
    _, root, info = project
    tools = {t.name: t for t in file_tools.create_file_tools('a')}
    listing = tools['list_projects'].invoke({})
    assert info.id in listing
    mapped = tools['project_map'].invoke({'project_id': info.id, 'path_prefix': 'package/'})
    assert 'FunctionDef add' in mapped and 'import math' in mapped
    found = tools['search_project'].invoke({'project_id': info.id, 'query': 'add', 'limit': 1})
    assert 'calc.py:3:' in found and 'offset=1' in found
    next_page = tools['search_project'].invoke({'project_id': info.id, 'query': 'add', 'offset': 1, 'limit': 1})
    assert 'test_calc.py:1:' in next_page
    other_tools = {t.name: t for t in file_tools.create_file_tools('b')}
    assert info.id not in other_tools['list_projects'].invoke({})
    with pytest.raises(FileNotFoundError):
        other_tools['project_map'].invoke({'project_id': info.id})
    for invalid in ['../escape', '/tmp/evil']:
        with pytest.raises(ValueError):
            tools['project_map'].invoke({'project_id': invalid})
    with pytest.raises(ValueError, match='реестр'):
        tools['read_file'].invoke({'file_path': f'.projects/{info.id}.json'})
    assert pw.projects(root) == [info]


@pytest.mark.parametrize('operation', ['replace_lines', 'append_to_file', 'write_file'])
def test_first_approved_edit_publishes_complete_project_with_receipt(
    project: tuple[Path, Path, pw.ProjectInfo], operation: str,
) -> None:
    source, root, info = project
    seen: list[str] = []
    tools = {t.name: t for t in file_tools.create_file_tools('a', approve=lambda p: seen.append(p) or True)}
    path = f'{info.input_path}/package/calc.py'
    arguments: dict[str, Any] = {'file_path': path}
    if operation == 'replace_lines':
        arguments.update(start_line=4, end_line=4, new_content='    return a + b\n')
    elif operation == 'append_to_file':
        arguments['text_to_append'] = '\n# reviewed\n'
    else:
        arguments['content'] = 'def add(a, b):\n    return a+b\n'
    response = tools[operation].invoke({'type':'tool_call','name':operation,'id':'edit','args':arguments})
    assert isinstance(response.artifact, FileReceipt) and response.artifact.still_matches()
    assert len(seen) == 1 and 'Изменения:' in seen[0] and 'Новое содержимое:' in seen[0]
    result = root / info.result_path
    assert (result / 'tests/test_calc.py').read_bytes() == (source / 'tests/test_calc.py').read_bytes()
    assert (root / info.input_path / 'package/calc.py').read_bytes() == (source / 'package/calc.py').read_bytes()
    assert len(file_tools.output_files('a')) == info.files
    # Even an old input path now reads the latest working copy, not stale code.
    assert tools['read_file'].invoke({'file_path': path}).endswith((result / 'package/calc.py').read_text())
    tools['append_to_file'].invoke({'file_path':path,'text_to_append':'# second edit\n'})
    assert 'second edit' in (result / 'package/calc.py').read_text()
    assert 'second edit' not in (source / 'package/calc.py').read_text()


@pytest.mark.parametrize('mode', ['reject', 'cancel', 'changed'])
def test_refused_cancelled_or_changed_project_has_no_results(
    project: tuple[Path, Path, pw.ProjectInfo], mode: str,
) -> None:
    _, root, info = project
    token = CancelToken()
    path = f'{info.input_path}/package/calc.py'
    def approve(_: str) -> bool:
        if mode == 'cancel':
            token['cancelled'] = True
        if mode == 'changed':
            (root / path).write_text('changed = True')
        return mode != 'reject'
    tools = {t.name: t for t in file_tools.create_file_tools('a', approve=approve, cancel=token)}
    if mode == 'reject':
        assert 'rejected' in tools['append_to_file'].invoke({'file_path':path,'text_to_append':'# added'})
    else:
        with pytest.raises((ValueError, RuntimeError)):
            tools['append_to_file'].invoke({'file_path':path,'text_to_append':'# added'})
    assert not (root / info.result_path).exists() and not file_tools.output_files('a')


def test_changed_dependency_blocks_first_project_publication(project: tuple[Path, Path, pw.ProjectInfo]) -> None:
    _, root, info = project
    (root / info.input_path / 'tests/test_calc.py').write_text('changed')
    tools = {t.name: t for t in file_tools.create_file_tools('a', approve=lambda _: True)}
    with pytest.raises(ValueError, match='изменилась'):
        tools['append_to_file'].invoke({'file_path':f'{info.input_path}/package/calc.py','text_to_append':'# added'})
    assert not (root / info.result_path).exists()


def test_tool_read_marks_truncation(project: tuple[Path, Path, pw.ProjectInfo]) -> None:
    _, root, _ = project
    (root / 'large.txt').write_text('x'*10000)
    tools = {t.name: t for t in file_tools.create_file_tools('a')}
    result = tools['read_file'].invoke({'file_path':'large.txt'})
    assert 'сокращён' in result and len(result) < 6500


def test_context_removes_whole_exchanges_preserves_task_and_tool_pairs() -> None:
    prefix = [SystemMessage(content='System rules'), HumanMessage(content='Fix add, then run tests')]
    window = AgentContext(prefix, max_chars=5000)
    messages = list(prefix)
    for i in range(15):
        messages.extend([AIMessage(content='', tool_calls=[{'id':str(i),'name':'read_file_lines',
                          'args':{'file_path':'calc.py','start_line':1,'end_line':40}}]),
                         ToolMessage(content=f'result {i}\n'+'x'*1000, tool_call_id=str(i))])
        messages = window.fit(messages)
        assert sum(message_size(m) for m in messages) <= 5000
        assert messages[:2] == prefix
        for j, message in enumerate(messages):
            if isinstance(message, ToolMessage):
                assert isinstance(messages[j-1], AIMessage)
                assert messages[j-1].tool_calls[0]['id'] == message.tool_call_id
    assert window.notes and messages[-1].tool_call_id == '14'
    assert not any(isinstance(m, ToolMessage) and m.tool_call_id == '0' for m in messages)
    with pytest.raises(ContextBudgetError):
        AgentContext([HumanMessage(content='x'*6000)], max_chars=5000).fit([HumanMessage(content='x'*6000), AIMessage(content='step')])


def test_context_compacts_empty_and_parallel_tool_results_together() -> None:
    prefix = [HumanMessage(content='Original task')]
    window = AgentContext(prefix, max_chars=2500)
    messages = [*prefix,
        AIMessage(content='',tool_calls=[{'id':str(i),'name':'list_directory','args':{}} for i in range(2)]),
        ToolMessage(content='',tool_call_id='0'), ToolMessage(content='',tool_call_id='1'),
        AIMessage(content='',tool_calls=[{'id':'last','name':'read_file_lines','args':{'file_path':'a.py'}}]),
        ToolMessage(content='x'*1800,tool_call_id='last'),
    ]
    compacted = window.fit(messages)
    assert compacted[0] is prefix[0] and compacted[-1].tool_call_id == 'last'
    remaining_ids = {m.tool_call_id for m in compacted if isinstance(m, ToolMessage)}
    assert '0' not in remaining_ids and '1' not in remaining_ids
    assert window.notes


def test_agent_can_repair_failed_project_test_and_report_actual_result(
    project: tuple[Path, Path, pw.ProjectInfo], monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, root, info = project
    import sandbox_runner
    executions = iter([ExecutionResult('ошибка выполнения',1,'','AssertionError',0.1),
                       ExecutionResult('завершено',0,'1 passed','',0.1)])
    monkeypatch.setattr(sandbox_runner, 'execute', lambda *a,**k: next(executions))
    path = f'{info.input_path}/package/calc.py'
    test_path = f'{info.input_path}/tests'
    calls = [
        ('read_file_lines', {'file_path':path,'start_line':1,'end_line':4}),
        ('run_pytest', {'file_path':test_path}),
        ('replace_lines', {'file_path':path,'start_line':4,'end_line':4,'new_content':'    return a+b\n'}),
        ('run_pytest', {'file_path':test_path}),
    ]
    model = MagicMock()
    model.bind_tools.return_value.invoke.side_effect = [
        *[AIMessage(content='', tool_calls=[{'id':str(i),'name':name,'args':args}]) for i,(name,args) in enumerate(calls)],
        AIMessage(content='Слишком оптимистичное утверждение'),
    ]
    seen: list[str] = []
    answer = LocalAgent(model).run('Исправь файл calc.py и проверь тесты',
        tools=file_tools.create_file_tools('a',approve=lambda p: seen.append(p) or True))
    assert '1 passed' in answer and 'AssertionError' in answer and len(seen) == 1
    assert 'сохранён, запись проверена' in answer and 'Слишком оптимистичное' not in answer
    assert (root / info.result_path / 'package/calc.py').read_text().endswith('return a+b\n')


def test_picker_captures_chat_and_async_import_is_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, page_loop: asyncio.AbstractEventLoop,
) -> None:
    from test_activity_ui import desktop
    monkeypatch.setattr(file_tools, 'WORKSPACE', tmp_path / 'chats')
    source = tmp_path / 'demo'; source.mkdir(); (source / 'hello.py').write_text('print(1)')
    app = desktop()
    app.page.loop = page_loop
    app._show_toast = MagicMock()
    async def choose() -> None:
        app._handle_project_click(None)
        while app.project_browser.dialog is None:
            await asyncio.sleep(0.01)
        dialog = app.project_browser.dialog
        field = dialog.content.content.controls[1].controls[1]
        field.value = str(source)
        app.chat_manager.current_chat_id = 'b'
        await dialog.actions[1].on_click(None)
        assert pw.projects(file_tools.workspace_for_chat('a')) == []
        app.project_browser.cancel()
        app.chat_manager.current_chat_id = 'a'
        app._handle_project_click(None)
        while app.project_browser.dialog is None:
            await asyncio.sleep(0.01)
        dialog = app.project_browser.dialog
        dialog.content.content.controls[1].controls[1].value = str(source)
        await dialog.actions[1].on_click(None)
        while app.is_processing:
            await asyncio.sleep(0.01)
    asyncio.run_coroutine_threadsafe(choose(), page_loop).result(timeout=5)
    assert app.agent_mode and app.agent_checkbox.value and app.project_status.visible
    assert 'demo' in app.project_status.value
    assert len(pw.projects(file_tools.workspace_for_chat('a'))) == 1
    app._shutdown()


@pytest.mark.skipif(os.environ.get('BUTUZ_SANDBOX_LIVE') != '1', reason='Requires prepared local Docker image')
def test_live_project_tests_use_project_root_and_latest_copy(project: tuple[Path, Path, pw.ProjectInfo]) -> None:
    source, root, info = project
    failed = execute(root, f'{info.input_path}/tests', tests=True)
    assert failed.exit_code == 1 and 'AssertionError' in failed.stdout
    tools = {t.name: t for t in file_tools.create_file_tools('a',approve=lambda _:True)}
    tools['replace_lines'].invoke({'file_path':f'{info.input_path}/package/calc.py',
        'start_line':4,'end_line':4,'new_content':'    return a+b\n'})
    passed = execute(root, f'{info.input_path}/tests', tests=True)
    assert passed.exit_code == 0 and '1 passed' in passed.stdout
    assert 'a - b' in (source / 'package/calc.py').read_text()
