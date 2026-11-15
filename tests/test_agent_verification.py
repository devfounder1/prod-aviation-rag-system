"""Regression: old tests and model prose cannot verify the latest approved edit."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

import file_tools
import sandbox_runner
from agent_verification import PostEditVerification, verification_requested
from ai_agent import LocalAgent
from file_receipts import verified_receipt
from sandbox_runner import ExecutionResult


@pytest.mark.parametrize('task', [
    'Исправь код и проверь его', 'Почини функцию add и запусти тесты',
    'Подправь скрипт .py и убедись, что всё работает',
    'Fix the code and check it', 'Repair the function and rerun pytest',
    'Не меняй оригинал, исправь код в копии и прогони тесты',
])
def test_current_edit_and_verification_request_enables_guard(task: str) -> None:
    assert verification_requested(task)


@pytest.mark.parametrize('task', [
    'Создай файл hello.py', 'Напиши сортировки на Python и сохрани',
    'Исправь текст документа и проверь по ГОСТ', 'Проверь тесты',
    'Напиши тесты для функции', 'Не исправляй код, объясни его',
    'Как исправь код и проверь работает?', 'How to fix code and test it?',
    'Объясни фразу «исправь код и проверь его»',
    'Объясни пример:\n```python\n# исправь код и запусти тесты\n```',
    'Исправь код, но тесты не запускай', 'Исправь код без запуска тестов',
    'Fix code but do not run tests', 'Fix code without tests',
    'Исправь код и проверь только синтаксис', 'Fix code and check syntax only',
    'Напиши ответ\nДоступные копии вложений: attached/fix_code_check.py',
    'Fix code in test.py', 'Please check fix.py',
    'Проверь код и исправь его, но тесты повторно не запускай',
    'Fix code and check it, but do not rerun tests',
    'Проверь код и исправь его без повторной проверки',
    'Исправь тестовый код и проверь только синтаксис',
    'Fix test.py and check syntax',
])
def test_unrelated_requests_prohibitions_and_examples_do_not_enable_guard(task: str) -> None:
    assert not verification_requested(task)


def call(name: str, **args: Any) -> AIMessage:
    return AIMessage(content='',tool_calls=[{'id':name,'name':name,'args':args}])


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(file_tools, 'WORKSPACE', tmp_path/'chats')
    root = file_tools.workspace_for_chat('a')
    (root/'code.py').write_text('value = 1\n')
    (root/'test_code.py').write_text('def test_value(): assert True\n')
    return root


def sandbox_result(root: Path, target: str = 'test_code.py', code: int = 0) -> ExecutionResult:
    return ExecutionResult('завершено' if code == 0 else 'ошибка выполнения',code,
        '1 passed' if code == 0 else '1 failed','',0.1,'pytest',str(root),target,
        tuple((p.relative_to(root).as_posix(),hashlib.sha256(p.read_bytes()).hexdigest())
              for p in sorted(root.rglob('*.py'))))


def test_old_test_then_edit_then_prose_forces_new_test_in_same_request(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs: list[int] = []
    def execute(root: Path, path: str, **kwargs: Any) -> ExecutionResult:
        runs.append(int((root/'code.py').read_text().split('=')[1]))
        return sandbox_result(root, path)
    monkeypatch.setattr(sandbox_runner,'execute',execute)
    model = MagicMock()
    model.bind_tools.return_value.invoke.side_effect = [
        call('run_pytest',file_path='test_code.py'),
        call('write_file',file_path='code.py',content='value = 2\n'),
        AIMessage(content='Всё исправлено и все тесты прошли'),
        AIMessage(content='Готово'),
    ]
    previews: list[str] = []
    answer = LocalAgent(model).run('Исправь код и проверь его',tools=file_tools.create_file_tools(
        'a',approve=lambda p:previews.append(p) or True))
    assert runs == [1,2] and len(previews) == 1
    assert 'Проверка после последней правки: pytest завершился успешно' in answer
    assert model.bind_tools.return_value.invoke.call_count == 4
    messages = model.bind_tools.return_value.invoke.call_args.args[0]
    assert any(isinstance(m,AIMessage) and m.response_metadata.get('automatic_post_edit_check') for m in messages)


def test_every_write_invalidates_prior_run_even_inside_one_tool_batch(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs = []
    def execute(root: Path, path: str, **kwargs: Any) -> ExecutionResult:
        runs.append((root/'code.py').read_text())
        return sandbox_result(root,path)
    monkeypatch.setattr(sandbox_runner,'execute',execute)
    first = AIMessage(content='',tool_calls=[
        {'id':'w1','name':'write_file','args':{'file_path':'code.py','content':'value = 2\n'}},
        {'id':'test','name':'run_pytest','args':{'file_path':'test_code.py'}},
        {'id':'w2','name':'write_file','args':{'file_path':'code.py','content':'value = 3\n'}},
    ])
    model = MagicMock()
    model.bind_tools.return_value.invoke.side_effect = [first,AIMessage(content='Done'),AIMessage(content='Done')]
    answer = LocalAgent(model).run('Fix code and test it',tools=file_tools.create_file_tools('a',approve=lambda _:True))
    assert runs == ['value = 2\n','value = 3\n']
    assert 'pytest завершился успешно' in answer


@pytest.mark.parametrize('available', [True,False])
def test_no_test_call_is_bounded_and_honest(workspace: Path, available: bool) -> None:
    model = MagicMock()
    model.bind_tools.return_value.invoke.side_effect = [
        call('write_file',file_path='code.py',content='value = 2\n'),
        AIMessage(content='Тесты прошли'),AIMessage(content='Тесты прошли'),AIMessage(content='Тесты прошли'),
    ]
    tools = file_tools.create_file_tools('a',approve=lambda _:True)
    if not available:
        tools = [t for t in tools if t.name != 'run_pytest']
    answer = LocalAgent(model).run('Исправь код и проверь его',tools=tools)
    assert 'Проверка после последней правки не подтверждена' in answer and 'Тесты прошли' not in answer
    assert model.bind_tools.return_value.invoke.call_count == (4 if available else 2)


def test_no_required_tests_does_not_add_repair(workspace: Path) -> None:
    model = MagicMock()
    model.bind_tools.return_value.invoke.side_effect = [
        call('write_file',file_path='hello.py',content='print(1)\n'),AIMessage(content='Done')]
    answer = LocalAgent(model).run('Создай файл hello.py',tools=file_tools.create_file_tools('a',approve=lambda _:True))
    assert 'Код и тесты не запускались' in answer and model.bind_tools.return_value.invoke.call_count == 2


def test_docker_unavailable_is_truthful_without_retry_loop(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*args: Any, **kwargs: Any) -> ExecutionResult:
        raise RuntimeError('Docker unavailable; no host fallback')
    monkeypatch.setattr(sandbox_runner,'execute',unavailable)
    model = MagicMock()
    model.bind_tools.return_value.invoke.side_effect = [
        call('write_file',file_path='code.py',content='value = 2\n'),
        call('run_pytest',file_path='test_code.py'),AIMessage(content='Тесты прошли')]
    answer = LocalAgent(model).run('Fix code and test it',tools=file_tools.create_file_tools('a',approve=lambda _:True))
    assert 'Docker unavailable' in answer and 'не подтверждена' in answer and 'Тесты прошли' not in answer
    assert model.bind_tools.return_value.invoke.call_count == 3


@pytest.mark.parametrize('failure_code', [1,2,5])
def test_post_edit_failures_are_reported_without_pretending_success(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, failure_code: int,
) -> None:
    monkeypatch.setattr(sandbox_runner,'execute',lambda root,path,**kw:sandbox_result(root,path,failure_code))
    model = MagicMock()
    model.bind_tools.return_value.invoke.side_effect = [
        call('write_file',file_path='code.py',content='value = 2\n'),
        call('run_pytest',file_path='test_code.py'),AIMessage(content='Все тесты прошли')]
    answer = LocalAgent(model).run('Fix code and test it',tools=file_tools.create_file_tools('a',approve=lambda _:True))
    assert 'не завершилась успешно' in answer and f'код завершения: {failure_code}' in answer
    assert 'Все тесты прошли' not in answer and model.bind_tools.return_value.invoke.call_count == 3


@pytest.mark.parametrize('finish', ['rejected','cancelled','limit'])
def test_rejection_cancellation_and_step_limit_cannot_start_hidden_tests(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, finish: str,
) -> None:
    execute = MagicMock()
    monkeypatch.setattr(sandbox_runner,'execute',execute)
    cancel = {'cancelled':False}
    model = MagicMock()
    def response(*args: Any, **kwargs: Any) -> AIMessage:
        if model.bind_tools.return_value.invoke.call_count == 1:
            return call('write_file',file_path='code.py',content='value = 2\n')
        cancel['cancelled'] = True
        return AIMessage(content='Done')
    model.bind_tools.return_value.invoke.side_effect = response
    answer = LocalAgent(model,max_iterations=1 if finish == 'limit' else 10).run(
        'Fix code and test it',tools=file_tools.create_file_tools('a',approve=lambda _:finish!='rejected',cancel=cancel),
        cancel_flag=cancel)
    assert not execute.called
    assert ('отменено' in answer.lower() if finish == 'cancelled' else 'не подтверждена' in answer or 'rejected' in answer)


def test_scope_hashes_target_and_tampering_are_verified(workspace: Path, tmp_path: Path) -> None:
    path = workspace/'code.py'
    policy = PostEditVerification(True)
    policy.executed(sandbox_result(workspace),'test_code.py')
    path.write_text('value = 2\n')
    receipt = verified_receipt(path,path.read_bytes(),'code.py')
    policy.written(receipt)
    policy.executed(ExecutionResult('завершено',0,'1 passed','',0.1),'test_code.py')
    assert policy.pending()  # A typed result without snapshot identity is insufficient.
    policy.executed(sandbox_result(workspace,'test_other.py'),'test_other.py')
    assert policy.pending()  # Different test file does not replace the original suite.
    other = tmp_path/'other'; other.mkdir(); (other/'code.py').write_bytes(path.read_bytes())
    policy.executed(sandbox_result(other),'test_code.py')
    assert policy.pending()
    policy.executed(sandbox_result(workspace),'test_code.py')
    assert not policy.pending()
    path.write_text('value = 3\n')
    assert policy.pending() and not policy.retry(True)


def test_python_run_and_syntax_are_not_pytest_proof(workspace: Path) -> None:
    path = workspace/'code.py'
    policy = PostEditVerification(True)
    policy.written(verified_receipt(path,path.read_bytes(),'code.py'))
    result = sandbox_result(workspace)
    from dataclasses import replace
    policy.executed(replace(result,kind='python'),'code.py')
    assert policy.pending()


def test_old_snapshot_returned_after_write_is_not_current_proof(workspace: Path) -> None:
    old = sandbox_result(workspace)
    path = workspace/'code.py'
    path.write_text('value = 2\n')
    policy = PostEditVerification(True)
    policy.written(verified_receipt(path,path.read_bytes(),'code.py'))
    policy.executed(old,'test_code.py')
    assert policy.pending()


def test_several_project_roots_need_their_own_post_edit_runs(workspace: Path) -> None:
    policy = PostEditVerification(True)
    roots = [workspace/f'results/projects/{name}' for name in ['first','second']]
    for root in roots:
        root.mkdir(parents=True)
        file = root/'code.py';file.write_text('value=1\n')
        policy.written(verified_receipt(file,file.read_bytes(),str(file.relative_to(workspace))))
    policy.executed(sandbox_result(roots[0],'tests'),'results/projects/first/tests')
    assert len(policy.pending()) == 1
    policy.executed(sandbox_result(roots[1],'tests'),'results/projects/second/tests')
    assert not policy.pending()


def test_several_prior_test_files_can_be_repeated_separately(workspace: Path) -> None:
    for name in ['test_a.py','test_b.py']:
        (workspace/name).write_text('def test_ok(): assert True\n')
    policy = PostEditVerification(True)
    for name in ['test_a.py','test_b.py']:
        policy.executed(sandbox_result(workspace,name),name)
    path = workspace/'code.py';path.write_text('value=2\n')
    policy.written(verified_receipt(path,path.read_bytes(),'code.py'))
    assert policy.automatic_targets() == ['test_a.py','test_b.py']
    policy.executed(sandbox_result(workspace,'test_a.py'),'test_a.py')
    assert policy.pending()
    policy.executed(sandbox_result(workspace,'test_b.py'),'test_b.py')
    assert not policy.pending()


def test_project_roots_cannot_be_verified_by_unrelated_workspace_tests(workspace: Path) -> None:
    path = workspace/'results/projects/project-id/package/code.py'
    path.parent.mkdir(parents=True);path.write_text('value=1')
    policy = PostEditVerification(True)
    policy.written(verified_receipt(path,path.read_bytes(),'results/projects/project-id/package/code.py'))
    policy.executed(sandbox_result(workspace),'test_code.py')
    assert policy.pending()
    root = workspace/'results/projects/project-id'
    policy.executed(sandbox_result(root,'tests'),'results/projects/project-id/tests')
    assert not policy.pending()


@pytest.mark.skipif(os.environ.get('BUTUZ_SANDBOX_LIVE')!='1',reason='Requires prepared local Docker image')
def test_real_runner_binds_result_to_copied_bytes(workspace: Path) -> None:
    result = sandbox_runner.execute(workspace,'test_code.py',tests=True)
    assert result.exit_code == 0 and result.kind == 'pytest'
    policy = PostEditVerification(True)
    path = workspace/'code.py'
    policy.written(verified_receipt(path,path.read_bytes(),'code.py'))
    policy.executed(result,'test_code.py')
    assert not policy.pending()
    path.write_text('value=99')
    assert policy.pending()


@pytest.mark.skipif(os.environ.get('BUTUZ_SANDBOX_LIVE')!='1',reason='Requires prepared local Docker image')
def test_real_post_edit_rerun_does_not_need_another_model_tool_call(workspace: Path) -> None:
    (workspace/'maths.py').write_text('def add(a,b):\n    return a-b\n')
    (workspace/'test_code.py').write_text('from maths import add\n\ndef test_add():\n    assert add(2,3)==5\n')
    model = MagicMock()
    model.bind_tools.return_value.invoke.side_effect = [
        call('run_pytest',file_path='test_code.py'),
        call('write_file',file_path='maths.py',content='def add(a,b):\n    return a+b\n'),
        AIMessage(content='Готово, больше инструментов не вызываю'),AIMessage(content='Готово'),
    ]
    answer = LocalAgent(model).run('Fix code and test it',tools=file_tools.create_file_tools('a',approve=lambda _:True))
    assert '1 failed' in answer and '1 passed' in answer
    assert 'Проверка после последней правки: pytest завершился успешно' in answer
