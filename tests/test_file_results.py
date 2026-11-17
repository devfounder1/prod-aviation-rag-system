from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from ai_agent import LocalAgent
import file_tools
from file_receipts import FileReceipt
from file_validation import prepare_text


@pytest.fixture(autouse=True)
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_tools, 'WORKSPACE', tmp_path / 'work')


def tool_map(**kwargs: Any) -> dict[str, Any]:
    return {tool.name: tool for tool in file_tools.create_file_tools('a', **kwargs)}


@pytest.mark.parametrize('operation', ['append_to_file', 'write_file'])
def test_attached_append_repairs_newlines_and_publishes_after_single_approval(tmp_path: Path, operation: str) -> None:
    original = tmp_path / 'lesson.py'
    original.write_text('value = 1\nprint(value)')
    seen: list[str] = []
    tools = tool_map(attachments=[{'path': str(original)}], approve=lambda preview: seen.append(preview) or True)
    source = file_tools.workspace_for_chat('a') / 'attached' / 'lesson.py'
    output = file_tools.workspace_for_chat('a') / 'results' / 'lesson.py'
    addition = r'\n'.join(["print('HELLO WORLD !!!!')"] * 10)
    args = ({'file_path': 'attached/lesson.py', 'text_to_append': addition} if operation == 'append_to_file'
            else {'file_path': 'attached/lesson.py', 'content': original.read_text() + '\n' + addition})
    reply = tools[operation].invoke({'name': operation, 'id': '1', 'type': 'tool_call', 'args': args})
    assert len(seen) == 1 and str(output) in seen[0]
    assert r'\n' not in seen[0]
    assert source.read_bytes() == original.read_bytes()
    assert file_tools.output_files('a') == [output]
    module = ast.parse(output.read_text())
    assert len([node for node in ast.walk(module) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == 'print']) == 11
    assert output.read_text().count('HELLO WORLD !!!!') == 10
    assert isinstance(reply.artifact, FileReceipt) and reply.artifact.still_matches()


@pytest.mark.parametrize('literal', [r'"a\nb"', r'r"C:\new\notes"', r'f"x\n{1}"'])
def test_python_string_escapes_are_never_globally_decoded(literal: str) -> None:
    valid = f'value = {literal}\nprint(value)\n'
    assert prepare_text(Path('safe.py'), valid) == valid
    broken = f'value = {literal}' + r'\n' + 'print(value)'
    assert prepare_text(Path('safe.py'), broken) == valid.rstrip('\n')


def test_ambiguous_or_invalid_python_never_reaches_confirmation() -> None:
    seen: list[str] = []
    tools = tool_map(approve=lambda preview: seen.append(preview) or True)
    for source in ['def broken(:\n pass', 'x = 1' + r'\n# comment\nprint(2)']:
        with pytest.raises(ValueError, match='не сохранён'):
            tools['write_file'].invoke({'file_path': 'bad.py', 'content': source})
    assert not seen and not file_tools.output_files('a')


def test_plain_text_escapes_are_user_data() -> None:
    content = r'write literal \n and C:\new\notes'
    assert prepare_text(Path('notes.txt'), content) == content


def test_line_replacement_keeps_next_statement_separate(tmp_path: Path) -> None:
    source = tmp_path / 'lesson.py'
    source.write_text('x = 1\nprint(x)\n')
    tools = tool_map(attachments=[{'path': str(source)}], approve=lambda _: True)
    tools['replace_lines'].invoke({'file_path': 'attached/lesson.py', 'start_line': 1,
                                  'end_line': 1, 'new_content': 'x = 2'})
    output = file_tools.output_files('a')[0]
    assert output.read_text() == 'x = 2\nprint(x)\n'
    assert source.read_text() == 'x = 1\nprint(x)\n'


def test_static_check_does_not_import_or_execute_user_code(tmp_path: Path) -> None:
    marker = tmp_path / 'must-not-exist'
    content = f'from pathlib import Path\nPath({str(marker)!r}).write_text("bad")\n'
    tools = tool_map(approve=lambda _: True)
    tools['write_file'].invoke({'file_path': 'never_run.py', 'content': content})
    result = tools['check_python_syntax'].invoke({'file_path': 'never_run.py'})
    assert 'Код и тесты не запускались' in result
    assert not marker.exists()


def test_agent_uses_verified_result_instead_of_false_success_after_rejection() -> None:
    model = MagicMock()
    model.bind_tools.return_value.invoke.side_effect = [
        AIMessage(content='', tool_calls=[{'name': 'write_file', 'id': '1',
            'args': {'file_path': 'rejected.py', 'content': 'print(1)'}}]),
        AIMessage(content='Файл успешно сохранён, все тесты прошли'),
    ]
    result = LocalAgent(model).run('Создай файл', tools=list(tool_map(approve=lambda _: False).values()))
    assert 'Файл не сохранён' in result and 'тесты прошли' not in result
    assert model.bind_tools.return_value.invoke.call_count == 1


def test_agent_can_correct_invalid_python_in_the_same_request() -> None:
    model = MagicMock()
    model.bind_tools.return_value.invoke.side_effect = [
        AIMessage(content='', tool_calls=[{'name': 'write_file', 'id': '1',
            'args': {'file_path': 'ok.py', 'content': 'def broken(:'}}]),
        AIMessage(content='', tool_calls=[{'name': 'write_file', 'id': '2',
            'args': {'file_path': 'ok.py', 'content': 'print(1)\n'}}]),
        AIMessage(content='Сохранено в придуманной папке, тесты прошли'),
    ]
    seen: list[str] = []
    result = LocalAgent(model).run('Создай файл', tools=list(tool_map(
        approve=lambda preview: seen.append(preview) or True).values()))
    assert len(seen) == 1
    assert 'ok.py' in result and 'сохранён, запись проверена' in result
    assert 'Код и тесты не запускались' in result
    assert 'придуманной' not in result and 'Последние ошибки' not in result


def test_changed_or_missing_file_cannot_get_verified_success() -> None:
    tools = tool_map()
    result = tools['write_file'].invoke({'name': 'write_file', 'id': '1', 'type': 'tool_call',
                                        'args': {'file_path': 'ok.py', 'content': 'print(1)'}})
    receipt = result.artifact
    assert isinstance(receipt, FileReceipt) and receipt.still_matches()
    Path(receipt.path).write_text('print(2)')
    assert not receipt.still_matches()


def test_failed_write_cannot_be_reported_as_saved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_tools, 'atomic_write', lambda path, content: None)
    model = MagicMock()
    model.bind_tools.return_value.invoke.side_effect = [
        AIMessage(content='', tool_calls=[{'name': 'write_file', 'id': '1',
            'args': {'file_path': 'missing.txt', 'content': 'data'}}]),
        AIMessage(content='Файл успешно сохранён'),
    ]
    result = LocalAgent(model).run('Создай файл', tools=list(tool_map(approve=lambda _: True).values()))
    assert 'Файл не сохранён' in result
    assert 'успешно сохранён' not in result and not file_tools.output_files('a')
