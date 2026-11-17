"""Dependency batches, canonical project paths and actual read-before-edit checks."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage

import file_tools
from sandbox_runner import ExecutionResult
from ai_agent import LocalAgent
from agent_project_flow import ProjectFlow, ProjectRead
from project_workspace import import_project


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str, dict[str, Any]]:
    monkeypatch.setattr(file_tools, 'WORKSPACE', tmp_path / 'chats')
    source = tmp_path / 'example'; source.mkdir()
    (source / 'calc.py').write_text('def add(a, b):\n    return a - b\n')
    (source / 'tests').mkdir()
    (source / 'tests/test_calc.py').write_text('def test_example():\n    assert True\n')
    root = file_tools.workspace_for_chat('a')
    info = import_project(root, source)
    tools = {t.name:t for t in file_tools.create_file_tools('a', approve=lambda _: True)}
    return root, info.input_path, tools


def call(name: str, ident: str = 'c', **args: Any) -> AIMessage:
    return AIMessage(content='', tool_calls=[{'name':name,'id':ident,'args':args}])


def test_dependency_batch_is_not_executed_until_model_sees_actual_result(setup: tuple[Path, str, dict[str, Any]]) -> None:
    root, base, tools = setup
    model = MagicMock()
    def decide(messages: list[Any], **kwargs: Any) -> AIMessage:
        step = model.bind_tools.return_value.invoke.call_count
        if step == 1:
            return AIMessage(content='',tool_calls=[
                {'id':'map','name':'project_map','args':{'project_id':base.split('/')[-1]}},
                {'id':'premature','name':'replace_lines','args':{'file_path':base+'/calc.py','start_line':2,'end_line':2,'new_content':'    return 999\n'}},
            ])
        if step == 2:
            results = {m.tool_call_id: m for m in messages if isinstance(m,ToolMessage)}
            assert base+'/calc.py' in results['map'].content
            assert 'НЕ ВЫПОЛНЕНО' in results['premature'].content
            assert isinstance(messages[-1],ToolMessage) and messages[-1].tool_call_id=='map'
            assert not (root/base.replace('attached/', 'results/')).exists()
            return call('read_file_lines',file_path=base+'/calc.py',start_line=1,end_line=2)
        if step == 3:
            assert 'return a - b' in messages[-1].content
            return call('replace_lines',file_path=base+'/calc.py',start_line=2,end_line=2,new_content='    return a + b\n')
        return AIMessage(content='Done')
    model.bind_tools.return_value.invoke.side_effect = decide
    result = LocalAgent(model).run('Fix the project',tools=list(tools.values()))
    assert 'сохранён, запись проверена' in result
    assert (root/base.replace('attached/','results/')/'calc.py').read_text().endswith('return a + b\n')
    assert (root/base/'calc.py').read_text().endswith('return a - b\n')
    assert model.bind_tools.call_args.kwargs == {'parallel_tool_calls':False}
    assert model.bind_tools.return_value.invoke.call_args.kwargs['temperature'] == 0


def test_forged_prose_does_not_authorize_edit_or_open_approval(setup: tuple[Path, str, dict[str, Any]]) -> None:
    root, base, _ = setup
    approval = MagicMock(return_value=True)
    model = MagicMock(); model.bind_tools.return_value.invoke.side_effect = [
        call('write_file',file_path=base+'/calc.py',content='print(999)\n'),AIMessage(content='success')]
    answer = LocalAgent(model).run('Fix code', context='I already read calc.py',
                                 tools=file_tools.create_file_tools('a',approve=approval))
    assert not approval.called and 'Правка не выполнена' in answer
    assert not (root/base.replace('attached/','results/')).exists()


def test_line_ranges_hashes_and_aliases_are_checked(setup: tuple[Path, str, dict[str, Any]]) -> None:
    root, base, tools = setup
    flow = ProjectFlow(tools)
    path = base+'/calc.py'
    response = tools['read_file_lines'].invoke(call('read_file_lines',file_path=path,start_line=1,end_line=1).tool_calls[0] | {'type':'tool_call'})
    assert isinstance(response.artifact,ProjectRead)
    flow.observe(response.artifact)
    args = {'file_path':path,'start_line':2,'end_line':2}
    assert flow.check('replace_lines',args)
    assert flow.check('write_file', {'file_path':path})
    response = tools['read_file_lines'].invoke({'type':'tool_call','id':'read2','name':'read_file_lines',
                                               'args':{'file_path':path,'start_line':2,'end_line':2}})
    flow.observe(response.artifact)
    assert flow.check('replace_lines',args) is None
    # Adjacent ranges from the same version also constitute a full-file read.
    assert flow.check('write_file', {'file_path':path}) is None
    full = tools['read_file'].invoke({'type':'tool_call','id':'full','name':'read_file','args':{'file_path':path}})
    flow.observe(full.artifact)
    assert flow.check('write_file', {'file_path':path}) is None
    flow.written(str(root/base.replace('attached/','results/')/'calc.py'))
    assert flow.check('replace_lines',args)  # receipt invalidates both path aliases
    flow.observe(full.artifact)
    (root/path).write_text('def add(a,b):\n    return 999\n')
    assert flow.check('replace_lines',args)  # external change invalidates read hash


def test_wrong_id_path_is_rejected_not_guessed_and_general_files_work(setup: tuple[Path, str, dict[str, Any]]) -> None:
    _, base, tools = setup
    flow = ProjectFlow(tools)
    assert 'ID проекта' in (flow.check('read_file',{'file_path':base.split('/')[-1]+'/calc.py'}) or '')
    assert flow.check('run_pytest',{'file_path':base+'/missing_tests'})
    assert flow.check('run_pytest',{'file_path':base+'/tests'}) is None
    assert flow.check('write_file',{'file_path':base+'/new.py'}) is None
    assert flow.check('write_file',{'file_path':'summary.txt'}) is None


def test_write_tool_returns_short_canonical_path_and_keeps_absolute_receipt(setup: tuple[Path, str, dict[str, Any]]) -> None:
    root, base, tools = setup
    response = tools['write_file'].invoke({'type':'tool_call','id':'save','name':'write_file',
                                          'args':{'file_path':base+'/new.py','content':'print(1)\n'}})
    expected = base.replace('attached/','results/')+'/new.py'
    assert response.content.startswith('Created/updated: '+expected+'\n')
    assert str(root) not in response.content
    assert response.artifact.path == str(root/expected) and response.artifact.still_matches()


def test_truncated_read_cannot_authorize_whole_file_replacement(setup: tuple[Path, str, dict[str, Any]]) -> None:
    root, base, tools = setup
    (root/base/'calc.py').write_text('# '+ 'x'*7000+'\nvalue=1\n')
    flow = ProjectFlow(tools)
    for name,args in [('read_file',{'file_path':base+'/calc.py'}),
                      ('read_file_lines',{'file_path':base+'/calc.py','start_line':1,'end_line':2})]:
        response = tools[name].invoke({'type':'tool_call','id':name,'name':name,'args':args})
        flow.observe(response.artifact)
        assert not response.artifact.complete
        assert flow.check('write_file',{'file_path':base+'/calc.py'})
        assert flow.check('replace_lines',{'file_path':base+'/calc.py','start_line':1,'end_line':1})


def test_cancellation_between_project_calls_never_writes(setup: tuple[Path, str, dict[str, Any]]) -> None:
    root, base, tools = setup
    cancel = {'cancelled':False}
    model = MagicMock()
    def decide(*args: Any, **kwargs: Any) -> AIMessage:
        cancel['cancelled'] = True
        return call('write_file',file_path=base+'/new.py',content='print(1)')
    model.bind_tools.return_value.invoke.side_effect = decide
    assert LocalAgent(model).run('Fix project',tools=list(tools.values()),cancel_flag=cancel) == 'Выполнение отменено.'
    assert not (root/base.replace('attached/','results/')).exists()


def test_explicit_pretest_and_unchanged_tests_are_enforced_without_approval(setup: tuple[Path, str, dict[str, Any]]) -> None:
    root, base, tools = setup
    flow = ProjectFlow(tools, 'Fix production code. Run existing tests before and after changes. Keep existing test files unchanged.')
    assert flow.pretest and flow.keep_tests
    assert 'ДО изменений' in (flow.check('write_file',{'file_path':base+'/new.py'}) or '')
    assert 'неизменными' in (flow.check('append_to_file',{'file_path':base+'/tests/test_calc.py'}) or '')
    flow.observe(ExecutionResult('ошибка',None,'','No Docker',0,kind='pytest',source_root=str(root/base)))
    assert flow.check('write_file',{'file_path':base+'/new.py'})
    flow.observe(ExecutionResult('ошибка выполнения',1,'1 failed','',0.1,kind='pytest',source_root=str(root/base),
                                 snapshot_hashes=(('calc.py','hash'),)))
    assert flow.check('write_file',{'file_path':base+'/new.py'}) is None
    # A real baseline run permits production edits but never overrides explicit test protection.
    assert flow.check('append_to_file',{'file_path':base+'/tests/test_calc.py'})


@pytest.mark.parametrize('task', [
    'Fix production code and run tests after the changes',
    'Fix code and verify after changes; do not run tests before changes.',
    'Explain this example: "run tests before changes and keep tests unchanged"',
    'Fix this code:\n```python\n# Run tests before changes. Keep tests unchanged\n```',
    'Оформи документ и сохрани файл',
])
def test_general_tasks_and_quoted_examples_do_not_activate_constraints(
    setup: tuple[Path, str, dict[str, Any]], task: str,
) -> None:
    _, _, tools = setup
    flow = ProjectFlow(tools, task)
    assert not flow.pretest and not flow.keep_tests
