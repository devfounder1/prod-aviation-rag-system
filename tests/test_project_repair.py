"""Exact edits and repair feedback retain evidence, never invent candidate fixes."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

import file_tools
from ai_agent import LocalAgent
from agent_project_flow import ProjectFlow
from file_receipts import verified_receipt
from project_repair import ProjectRepair, RepairReplacement, execution_feedback, with_repair_state
from sandbox_runner import ExecutionResult
from project_workspace import import_project
from test_agent_project_flow import setup  # synthetic project fixture, never host execution


def invoke(tools: dict[str, Any], name: str, **args: Any) -> Any:
    return tools[name].invoke({'type':'tool_call','id':'c','name':name,'args':args})


def test_exact_edit_preserves_unrelated_source_and_requires_current_read(setup: tuple[Path,str,dict[str,Any]]) -> None:
    root, base, tools = setup
    path = base+'/calc.py'
    flow = ProjectFlow(tools)
    args = {'file_path':path,'old_text':'a - b','new_text':'a + b'}
    assert flow.check('replace_text',args)
    flow.observe(invoke(tools,'read_file',file_path=path).artifact)
    assert flow.check('replace_text',args) is None
    result = invoke(tools,'replace_text',**args)
    assert result.artifact.still_matches()
    assert (root/base.replace('attached/','results/')/'calc.py').read_text() == 'def add(a, b):\n    return a + b\n'
    assert (root/base/'calc.py').read_text().endswith('a - b\n')
    flow.written(result.artifact.path)
    assert flow.check('replace_text',{'file_path':path,'old_text':'a + b','new_text':'a * b'})
    flow.observe(invoke(tools,'read_file',file_path=path).artifact)
    assert flow.check('replace_text',{'file_path':path,'old_text':'a + b','new_text':'a * b'}) is None


@pytest.mark.parametrize('old,new', [('', 'pass'),('a - b','a - b'),('missing','pass'),('return a - b','return @')])
def test_bad_exact_edits_do_not_reach_approval(setup: tuple[Path,str,dict[str,Any]],old: str,new: str) -> None:
    root, base, _ = setup
    approve = MagicMock(return_value=True)
    tools = {t.name:t for t in file_tools.create_file_tools('a',approve=approve)}
    with pytest.raises(ValueError):
        invoke(tools,'replace_text',file_path=base+'/calc.py',old_text=old,new_text=new)
    assert not approve.called and not (root/base.replace('attached/','results/')).exists()


def test_ambiguous_match_and_escapes_are_not_guessed(setup: tuple[Path,str,dict[str,Any]]) -> None:
    root, _, tools = setup
    path = root/'literal.py'
    path.write_text('pattern = r"a\\nb"\nx = 1\ny = 1\n')
    with pytest.raises(ValueError,match='unique'):
        invoke(tools,'replace_text',file_path='literal.py',old_text='= 1',new_text='= 2')
    invoke(tools,'replace_text',file_path='literal.py',old_text='x = 1',new_text='x = 2')
    assert path.read_text() == 'pattern = r"a\\nb"\nx = 2\ny = 1\n'


def test_exact_edit_preserves_crlf_bytes(setup: tuple[Path,str,dict[str,Any]]) -> None:
    root,_,tools=setup
    path=root/'windows.py'
    path.write_bytes(b'x = 1\r\ny = 2\r\n')
    result=invoke(tools,'replace_text',file_path='windows.py',old_text='x = 1',new_text='x = 3')
    assert result.artifact.still_matches()
    assert path.read_bytes()==b'x = 3\r\ny = 2\r\n'


def test_repair_schema_requires_single_line_anchor_without_changing_universal_tool() -> None:
    from pydantic import ValidationError
    assert RepairReplacement(file_path='x.py',old_text='if ready:',new_text='if not ready:').old_text=='if ready:'
    with pytest.raises(ValidationError):
        RepairReplacement(file_path='x.py',old_text='if ready:\n    continue',new_text='if not ready:\n    continue')


def test_verified_saved_source_survives_context_without_granting_another_edit_read(
    setup: tuple[Path,str,dict[str,Any]],
) -> None:
    root,base,tools=setup
    path=base+'/calc.py';state=ProjectRepair();flow=ProjectFlow(tools)
    read=invoke(tools,'read_file',file_path=path)
    state.observe('read_file',{'file_path':path},read.artifact,content=read.content);flow.observe(read.artifact)
    result=invoke(tools,'replace_text',file_path=path,old_text='a - b',new_text='a + b')
    state.observe('replace_text',{},result.artifact,content=result.content);flow.written(result.artifact.path)
    assert 'SAVED SOURCE' in result.content and 'return a + b' in result.content
    prefix=[SystemMessage(content='policy'),HumanMessage(content='Fix code')]
    decision=state.decision_messages(prefix,prefix,16000)
    assert 'return a + b' in '\n'.join(str(m.content) for m in decision)
    assert flow.check('replace_text',{'file_path':path,'old_text':'a + b','new_text':'a * b'})
    (root/base.replace('attached/','results/')/'calc.py').write_text('external_unseen=1\n')
    decision=state.decision_messages(prefix,prefix,16000)
    assert not any('return a + b' in str(m.content) or 'external_unseen' in str(m.content) for m in decision)


@pytest.mark.parametrize('mode',['reject','cancel'])
def test_exact_edit_rejection_and_cancellation_prevent_publication(setup: tuple[Path,str,dict[str,Any]],mode: str) -> None:
    root,base,_ = setup
    cancel = {'cancelled':False}
    def approve(_: str) -> bool:
        cancel['cancelled'] = mode == 'cancel'
        return mode != 'reject'
    tools = {t.name:t for t in file_tools.create_file_tools('a',approve=approve,cancel=cancel)}
    args = {'file_path':base+'/calc.py','old_text':'a - b','new_text':'a + b'}
    if mode == 'reject':
        assert 'rejected' in invoke(tools,'replace_text',**args).content
    else:
        with pytest.raises(RuntimeError,match='cancelled'):
            invoke(tools,'replace_text',**args)
    assert not (root/base.replace('attached/','results/')).exists()


def test_exact_edits_obey_unchanged_tests_and_pretest_policy(setup: tuple[Path,str,dict[str,Any]]) -> None:
    _,base,tools = setup
    flow = ProjectFlow(tools,'Fix code. Run tests before and after changes. Keep existing tests unchanged.')
    assert 'ДО изменений' in (flow.check('replace_text',{'file_path':base+'/calc.py'}) or '')
    assert 'неизменными' in (flow.check('replace_text',{'file_path':base+'/tests/test_calc.py'}) or '')


def test_project_pytest_rejects_chat_root_without_rewriting_target(setup: tuple[Path,str,dict[str,Any]]) -> None:
    _,base,tools=setup
    flow=ProjectFlow(tools,'Fix the project and test it')
    args={'file_path':'.'}
    assert 'корень чата' in (flow.check('run_pytest',args) or '') and args=={'file_path':'.'}
    assert flow.check('run_pytest',{'file_path':base}) is None


def test_failed_tests_resume_a_premature_final_and_validate_second_edit(
    setup: tuple[Path,str,dict[str,Any]],monkeypatch: pytest.MonkeyPatch,
) -> None:
    root,base,tools = setup
    import sandbox_runner
    exits = iter([1,1,0])
    def execute(*args: Any, **kwargs: Any) -> ExecutionResult:
        current = root/(base.replace('attached/','results/') if (root/base.replace('attached/','results/')).exists() else base)
        code = next(exits)
        return ExecutionResult('завершено' if code==0 else 'ошибка выполнения',code,
            '1 passed' if code==0 else 'FAILED tests/test_calc.py::test_add - AssertionError\n1 failed','',0.1,
            kind='pytest',source_root=str(current),target_path='tests',snapshot_hashes=tuple(
                (p.relative_to(current).as_posix(),hashlib.sha256(p.read_bytes()).hexdigest())
                for p in sorted(current.rglob('*')) if p.is_file()))
    monkeypatch.setattr(sandbox_runner,'execute',execute)
    def call(name: str, **args: Any) -> AIMessage:
        return AIMessage(content='',tool_calls=[{'id':'c','name':name,'args':args}])
    path = base+'/calc.py'
    model = MagicMock();model.bind_tools.return_value.invoke.side_effect = [
        call('run_pytest',file_path=base+'/tests'),call('read_file',file_path=path),
        call('replace_text',file_path=path,old_text='a - b',new_text='a * b'),
        call('run_pytest',file_path=base+'/tests'),AIMessage(content='All tests pass!'),
        call('read_file',file_path=path),call('replace_text',file_path=path,old_text='a * b',new_text='a + b'),
        call('run_pytest',file_path=base+'/tests'),AIMessage(content='Done'),
    ]
    result = LocalAgent(model).run('Fix the code and run tests',tools=list(tools.values()))
    assert model.bind_tools.return_value.invoke.call_count == 9
    assert 'pytest завершился успешно' in result and 'All tests pass!' not in result
    names = {t.name for t in model.bind_tools.call_args.args[0]}
    assert 'replace_text' in names and 'replace_lines' not in names and 'update_attached_file' not in names
    assert (root/base.replace('attached/','results/')/'calc.py').read_text().endswith('a + b\n')
    assert (root/base/'calc.py').read_text().endswith('a - b\n')


def test_general_project_document_question_keeps_universal_tools(setup: tuple[Path,str,dict[str,Any]]) -> None:
    _,_,tools = setup
    model = MagicMock();model.bind_tools.return_value.invoke.return_value = AIMessage(content='Document explanation')
    assert LocalAgent(model).run('Explain the documents',tools=list(tools.values())) == 'Document explanation'
    assert 'replace_lines' in {t.name for t in model.bind_tools.call_args.args[0]}


def test_mismatch_hides_writes_until_actual_reread_of_same_file(setup: tuple[Path,str,dict[str,Any]]) -> None:
    root,base,tools=setup
    from agent_project_flow import ProjectRead
    state=ProjectRepair()
    path=base+'/calc.py'
    state.observe('replace_text',{'file_path':path,'old_text':'invented'},None,'old_text must match')
    assert 'replace_text' not in state.tool_names() and 'write_file' not in state.tool_names()
    state.observe('read_file',{},ProjectRead(str(root/base/'tests/test_calc.py'),'hash',1,2,True))
    assert state.read_required
    state.observe('read_file',{},invoke(tools,'read_file',file_path=path).artifact)
    assert not state.read_required and 'replace_text' in state.tool_names()
    # A receipt on another file/project cannot serve as a source read.
    state.observe('replace_text',{'file_path':path,'old_text':'invented'},None,'old_text must match')
    state.observe('replace_text',{},verified_receipt(root/base/'calc.py',(root/base/'calc.py').read_bytes(),path))
    assert state.read_required


def test_hidden_write_cannot_bypass_recovery_read(setup: tuple[Path,str,dict[str,Any]],monkeypatch: pytest.MonkeyPatch) -> None:
    root,base,_=setup
    import sandbox_runner
    def execute(*args: Any,**kwargs: Any) -> ExecutionResult:
        current=root/base.replace('attached/','results/')
        return ExecutionResult('завершено',0,'1 passed','',0.1,kind='pytest',source_root=str(current),target_path='tests',
                               snapshot_hashes=tuple((p.relative_to(current).as_posix(),hashlib.sha256(p.read_bytes()).hexdigest())
                                                     for p in current.rglob('*') if p.is_file()))
    monkeypatch.setattr(sandbox_runner,'execute',execute)
    monkeypatch.setattr(ProjectRepair,'source_refresh',lambda self: None)  # fallback when automatic read budget is exhausted
    approve=MagicMock(return_value=True)
    tools=file_tools.create_file_tools('a',approve=approve)
    path=base+'/calc.py'
    def call(name: str,**args: Any) -> AIMessage:
        return AIMessage(content='',tool_calls=[{'id':'c','name':name,'args':args}])
    replies=iter([
        call('read_file',file_path=path),
        call('replace_text',file_path=path,old_text='invented source',new_text='new source'),
        call('replace_text',file_path=path,old_text='a - b',new_text='a + b'),
        call('read_file',file_path=path),
        call('replace_text',file_path=path,old_text='a - b',new_text='a + b'),
        call('run_pytest',file_path=base+'/tests'),AIMessage(content='Done'),
    ])
    model=MagicMock()
    def decide(*args: Any,**kwargs: Any) -> AIMessage:
        if model.bind_tools.return_value.invoke.call_count in {3,4}:
            assert {t.name for t in model.bind_tools.call_args.args[0]}=={'read_file','read_file_lines'}
            assert not approve.called and not (root/base.replace('attached/','results/')).exists()
        return next(replies)
    model.bind_tools.return_value.invoke.side_effect=decide
    answer=LocalAgent(model).run('Fix code and run tests',tools=tools)
    assert approve.call_count==1 and 'pytest завершился успешно' in answer


def test_source_refresh_only_repeats_a_successfully_selected_read_and_is_bounded(setup: tuple[Path,str,dict[str,Any]]) -> None:
    _,base,tools=setup
    state=ProjectRepair();path=base+'/calc.py'
    state.observe('replace_text',{'file_path':path},None,'old_text mismatch')
    assert state.source_refresh() is None  # never invent a new read target
    args={'file_path':path}
    state.observe('read_file',args,invoke(tools,'read_file',**args).artifact)
    state.observe('replace_text',{'file_path':path},None,'old_text mismatch')
    for _ in range(3):
        assert state.source_refresh()==('read_file',args)
    assert state.source_refresh() is None


def test_automatic_reread_restores_actual_source_before_model_repairs(setup: tuple[Path,str,dict[str,Any]],monkeypatch: pytest.MonkeyPatch) -> None:
    root,base,tools=setup
    import sandbox_runner
    def execute(*args: Any,**kwargs: Any) -> ExecutionResult:
        current=root/base.replace('attached/','results/')
        return ExecutionResult('завершено',0,'1 passed','',0.1,kind='pytest',source_root=str(current),target_path='tests',
                               snapshot_hashes=tuple((p.relative_to(current).as_posix(),hashlib.sha256(p.read_bytes()).hexdigest())
                                                     for p in current.rglob('*') if p.is_file()))
    monkeypatch.setattr(sandbox_runner,'execute',execute)
    path=base+'/calc.py'
    def call(name: str,**args: Any) -> AIMessage:
        return AIMessage(content='',tool_calls=[{'id':'c','name':name,'args':args}])
    replies=iter([call('read_file',file_path=path),call('replace_text',file_path=path,old_text='invented',new_text='wrong'),
                  call('replace_text',file_path=path,old_text='a - b',new_text='a + b'),
                  call('run_pytest',file_path=base+'/tests'),AIMessage(content='Done')])
    model=MagicMock()
    def decide(messages: list[Any],**kwargs: Any) -> AIMessage:
        if model.bind_tools.return_value.invoke.call_count==3:
            assert isinstance(messages[-1],ToolMessage) and 'return a - b' in messages[-1].content
            assert messages[-2].response_metadata.get('automatic_source_refresh') is True
            assert messages[-2].tool_calls[0]['args']=={'file_path':path}
        return next(replies)
    model.bind_tools.return_value.invoke.side_effect=decide
    answer=LocalAgent(model).run('Fix code and run tests',tools=list(tools.values()))
    assert 'pytest завершился успешно' in answer and model.bind_tools.return_value.invoke.call_count==5


def test_ledger_tracks_latest_suite_scope_and_current_bytes(tmp_path: Path) -> None:
    flow = ProjectRepair()
    path = tmp_path/'code.py';path.write_text('value=1\n')
    receipt = verified_receipt(path,path.read_bytes(),'code.py')
    flow.observe('replace_text',{},receipt)
    failed = ExecutionResult('ошибка выполнения',1,'FAILED tests/test_one.py::test_x\n1 failed','',0.1,
        kind='pytest',source_root=str(tmp_path),target_path='tests/test_one.py',snapshot_hashes=(('code.py',receipt.sha256),))
    flow.observe('run_pytest',{},failed)
    assert flow.failing() and all(flow.retry_finish() for _ in range(6)) and not flow.retry_finish()
    assert '"snapshot_includes_current_writes": true' in flow.state()
    path.write_text('value=2\n')
    assert '"snapshot_includes_current_writes": false' in flow.state()
    flow.observe('run_pytest',{},replace(failed,exit_code=0,target_path='tests/test_two.py'))
    assert flow.failing()  # another file's pass cannot erase the failed suite
    flow.observe('run_pytest',{},replace(failed,exit_code=0,target_path='tests',stdout='2 passed'))
    assert not flow.failing()
    assert len(flow.latest)==1


def test_collection_errors_remain_failures_for_model_repair(tmp_path: Path) -> None:
    state=ProjectRepair()
    error=ExecutionResult('ошибка выполнения',2,'ERROR tests/test_api.py\nImportError during collection','',0.1,
        kind='pytest',source_root=str(tmp_path),target_path='tests',snapshot_hashes=(('code.py','hash'),))
    state.observe('run_pytest',{},error)
    assert state.failing() and state.retry_finish()
    request=state.analysis_messages('Fix code and test')
    assert request and 'ImportError during collection' in str(request[-1].content)


def test_unchanged_root_failure_hides_repeated_execution_until_new_write(tmp_path: Path) -> None:
    root=tmp_path/'results/projects/demo';root.mkdir(parents=True)
    path=root/'calc.py';path.write_text('x=1\n')
    state=ProjectRepair('Fix the project and test it')
    run=ExecutionResult('ошибка выполнения',1,'1 failed','',0.1,kind='pytest',source_root=str(root),target_path='.',
                        snapshot_hashes=(('calc.py',hashlib.sha256(path.read_bytes()).hexdigest()),))
    state.observe('run_pytest',{},run)
    assert state.unchanged_root_failure() and 'run_pytest' not in state.tool_names() and 'replace_text' in state.tool_names()
    path.write_text('x=2\n')
    state.observe('replace_text',{},verified_receipt(path,path.read_bytes(),'results/projects/demo/calc.py'))
    assert not state.unchanged_root_failure() and 'run_pytest' in state.tool_names()
    narrow=ProjectRepair('Fix code and run only tests/test_calc.py')
    multiple=ProjectRepair('Fix the project and test it',single_project=False)
    for other in (narrow,multiple):
        other.observe('run_pytest',{},run)
        assert 'run_pytest' in other.tool_names()


def test_saved_edit_is_tested_before_next_model_action_without_queuing_it(
    setup: tuple[Path,str,dict[str,Any]],monkeypatch: pytest.MonkeyPatch,
) -> None:
    root,base,tools=setup
    import sandbox_runner
    codes=iter([1,1,0]);runs=[]
    def execute(*args: Any,**kwargs: Any) -> ExecutionResult:
        current=root/(base.replace('attached/','results/') if (root/base.replace('attached/','results/')).exists() else base)
        code=next(codes);runs.append(code)
        return ExecutionResult('завершено' if code==0 else 'ошибка выполнения',code,'1 passed' if code==0 else '1 failed',
            '',0.1,kind='pytest',source_root=str(current),target_path='tests',
            snapshot_hashes=(('calc.py',hashlib.sha256((current/'calc.py').read_bytes()).hexdigest()),))
    monkeypatch.setattr(sandbox_runner,'execute',execute)
    path=base+'/calc.py'
    def call(name: str,**args: Any) -> AIMessage:
        return AIMessage(content='',tool_calls=[{'id':'c','name':name,'args':args}])
    responses=iter([call('run_pytest',file_path=base+'/tests'),call('read_file',file_path=path),
        call('replace_text',file_path=path,old_text='a - b',new_text='a * b'),
        call('read_file',file_path=path), # deliberately deferred, not run after validation
        call('read_file',file_path=path), # a new actual model decision
        call('replace_text',file_path=path,old_text='a * b',new_text='a + b'),AIMessage(content='Done'),AIMessage(content='Done')])
    model=MagicMock()
    def decide(messages: list[Any],**kwargs: Any) -> AIMessage:
        if 2 <= model.bind_tools.return_value.invoke.call_count <= 6:
            assert model.bind_tools.call_args.kwargs['tool_choice']=='required'
        if model.bind_tools.return_value.invoke.call_count==8:
            assert model.bind_tools.call_args.kwargs['tool_choice']=='auto'
        if model.bind_tools.return_value.invoke.call_count==5:
            assert runs==[1,1]
            assert messages[-2].response_metadata.get('automatic_post_edit_check') is True
            assert isinstance(messages[-1],ToolMessage) and '1 failed' in messages[-1].content
            assert not any(isinstance(m,ToolMessage) and 'return a * b' in str(m.content) for m in messages)
        return next(responses)
    model.bind_tools.return_value.invoke.side_effect=decide
    answer=LocalAgent(model).run('Fix code and run tests',tools=list(tools.values()))
    assert runs==[1,1,0] and 'pytest завершился успешно' in answer


def test_model_feedback_keeps_trace_and_failure_summary() -> None:
    run = ExecutionResult('ошибка выполнения',1,'AssertionError near the beginning\n'+'noise\n'*2000+
                          'FAILED tests/test_tail.py::test_last\n1 failed','',0.1)
    brief = execution_feedback(run)
    assert 'AssertionError' in brief and 'FAILED tests/test_tail.py::test_last' in brief and 'сокращён' in brief
    assert len(brief)<5000


def test_failure_analysis_uses_current_returned_source_and_is_bounded(
    setup: tuple[Path,str,dict[str,Any]],
) -> None:
    root,base,tools=setup
    state=ProjectRepair()
    path=base+'/calc.py'
    read=invoke(tools,'read_file',file_path=path)
    state.observe('read_file',{'file_path':path},read.artifact,content=read.content)
    run=ExecutionResult('ошибка выполнения',1,'assert -1 == 5\nFAILED tests/test_calc.py::test_add\n1 failed','',0.1,
                        kind='pytest',source_root=str(root/base),target_path='tests',
                        snapshot_hashes=(('calc.py',read.artifact.sha256),))
    state.observe('run_pytest',{},run)
    request=state.analysis_messages('Fix code and test')
    assert request and 'return a - b' in str(request[-1].content) and 'assert -1 == 5' in str(request[-1].content)
    assert state.analysis_messages('Fix code and test') is None
    # Changed bytes invalidate cached source even without a mutation receipt.
    (root/base/'calc.py').write_text('changed_unseen = 1\n')
    for index in range(5):
        state.observe('run_pytest',{},replace(run,stdout=f'failure {index}'))
        request=state.analysis_messages('Fix code and test')
        assert request and 'return a - b' not in str(request[-1].content) and 'changed_unseen' not in str(request[-1].content)
    state.observe('run_pytest',{},replace(run,stdout='failure beyond budget'))
    assert state.analysis_messages('Fix code and test') is None


def test_model_analysis_cannot_write_or_establish_success(
    setup: tuple[Path,str,dict[str,Any]],monkeypatch: pytest.MonkeyPatch,
) -> None:
    root,base,tools=setup
    import sandbox_runner
    monkeypatch.setattr(sandbox_runner,'execute',lambda *a,**k: ExecutionResult(
        'ошибка выполнения',1,'1 failed','',0.1,kind='pytest',source_root=str(root/base),target_path='tests',
        snapshot_hashes=(('calc.py',hashlib.sha256((root/base/'calc.py').read_bytes()).hexdigest()),)))
    model=MagicMock()
    model.invoke.return_value=AIMessage(content='All fixed, tests passed!',tool_calls=[
        {'id':'bad','name':'write_file','args':{'file_path':base+'/calc.py','content':'invented=1'}}])
    model.bind_tools.return_value.invoke.side_effect=[
        AIMessage(content='',tool_calls=[{'id':'test','name':'run_pytest','args':{'file_path':base+'/tests'}}]),
        *[AIMessage(content='Done') for _ in range(7)]]
    answer=LocalAgent(model).run('Fix code and run tests',tools=list(tools.values()))
    assert model.invoke.call_count==1 and '1 failed' in answer and 'All fixed' not in answer
    assert not (root/base.replace('attached/','results/')).exists()


def test_analysis_does_not_treat_pre_edit_failures_as_current(
    setup: tuple[Path,str,dict[str,Any]],
) -> None:
    root,base,tools=setup
    state=ProjectRepair()
    read=invoke(tools,'read_file',file_path=base+'/calc.py')
    failed=ExecutionResult('ошибка выполнения',1,'1 failed','',0.1,kind='pytest',source_root=str(root/base),
        target_path='tests',snapshot_hashes=(('calc.py',read.artifact.sha256),))
    state.observe('run_pytest',{},failed)
    state.diagnosis='Old hypothesis'
    receipt=invoke(tools,'replace_text',file_path=base+'/calc.py',old_text='a - b',new_text='a + b').artifact
    state.observe('replace_text',{},receipt)
    assert state.analysis_messages('Fix code and test') is None and not state.diagnosis
    new=replace(failed,source_root=str(root/base.replace('attached/','results/')),
                snapshot_hashes=(('calc.py',receipt.sha256),),stdout='new failure')
    state.observe('run_pytest',{},new)
    assert state.analysis_messages('Fix code and test') is not None
    state.diagnosis='Another hypothesis'
    state.observe('run_pytest',{},replace(new,exit_code=0,stdout='1 passed'))
    assert not state.diagnosis and state.analysis_messages('Fix code and test') is None


def test_whole_project_scope_requires_actual_root_run_with_current_bytes(tmp_path: Path) -> None:
    root=tmp_path/'results/projects/demo';root.mkdir(parents=True)
    path=root/'calc.py';path.write_text('value=1\n')
    receipt=verified_receipt(path,path.read_bytes(),'results/projects/demo/calc.py')
    flow=ProjectRepair('Review the project and fix code. Run existing tests.')
    flow.observe('replace_text',{},receipt)
    run=ExecutionResult('завершено',0,'1 passed','',0.1,kind='pytest',source_root=str(root),target_path='tests/test_one.py',
                        snapshot_hashes=(('calc.py',receipt.sha256),))
    flow.observe('run_pytest',{},run)
    assert not flow.failing() and flow.full_scope_pending()==['results/projects/demo'] and flow.retry_finish()
    flow.observe('run_pytest',{},replace(run,target_path='.'))
    assert not flow.full_scope_pending()
    path.write_text('value=2\n')
    assert flow.full_scope_pending()==['results/projects/demo']


@pytest.mark.parametrize('task',[
    'Fix the code and test only tests/test_one.py',
    'Review the project but run only tests/test_one.py',
    'Fix the project and run tests/test_one.py',
    'Исправь проект, запускай только тесты tests/test_one.py',
    'Explain: "fix the entire project"',
])
def test_narrow_or_quoted_requests_do_not_require_full_project_scope(task: str) -> None:
    assert not ProjectRepair(task).whole_project


def test_repair_ledger_preserves_latest_feedback_and_tool_pairs() -> None:
    original = [SystemMessage(content='policy'),HumanMessage(content='Fix this project')]
    initial = with_repair_state(original,'state')
    assert initial[-1] is original[-1] and len(original)==2
    decision = AIMessage(content='',tool_calls=[{'id':'x','name':'read_file','args':{}}])
    feedback = ToolMessage(content='actual source',tool_call_id='x')
    exchanged = [*original,decision,feedback]
    request = with_repair_state(exchanged,'state')
    assert request[-2:] == [decision,feedback] and len(exchanged)==4
    assert request[-3].content=='state'


def test_decision_rebuild_drops_old_guesses_keeps_actual_last_exchange(
    setup: tuple[Path,str,dict[str,Any]],
) -> None:
    _,base,tools=setup
    from agent_context import message_size
    prefix=[SystemMessage(content='policy'),HumanMessage(content='Fix the project, preserve tests')]
    read=invoke(tools,'read_file',file_path=base+'/calc.py')
    state=ProjectRepair()
    state.observe('read_file',{'file_path':base+'/calc.py'},read.artifact,content=read.content)
    old=AIMessage(content='Invented old proposal',tool_calls=[{'id':'old','name':'replace_text','args':{}}])
    latest=AIMessage(content='',tool_calls=[{'id':'new','name':'read_file','args':{}}])
    result=ToolMessage(content=read.content,tool_call_id='new')
    messages=[*prefix,old,ToolMessage(content='Rejected invented old code',tool_call_id='old'),latest,result,
              AIMessage(content='Premature claim of success'),SystemMessage(content='Retry policy')]
    rebuilt=state.decision_messages(prefix,messages,16000)
    assert rebuilt[:2]==prefix and rebuilt[-2:]==[latest,result]
    rendered='\n'.join(str(m.content) for m in rebuilt)
    assert 'Invented old proposal' not in rendered and 'Premature claim' not in rendered and 'Retry policy' in rendered
    assert 'return a - b' in rendered and sum(message_size(m) for m in rebuilt)<=16000
    # Invalidating an alias removes the cached source, not just its read permission.
    receipt=invoke(tools,'replace_text',file_path=base+'/calc.py',old_text='a - b',new_text='a + b').artifact
    state.observe('replace_text',{},receipt)
    assert not state.sources


@pytest.mark.skipif(os.environ.get('BUTUZ_SANDBOX_LIVE')!='1',reason='Requires prepared local Docker image')
def test_exact_edit_and_automatic_verification_in_real_project_sandbox(tmp_path: Path,monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_tools,'WORKSPACE',tmp_path/'chats')
    source=tmp_path/'source';(source/'tests').mkdir(parents=True)
    (source/'calc.py').write_text('def add(a,b):\n    return a-b\n')
    (source/'tests/test_calc.py').write_text('from calc import add\n\ndef test_add():\n    assert add(2,3)==5\n')
    root=file_tools.workspace_for_chat('a'); info=import_project(root,source)
    before={p.relative_to(source).as_posix():p.read_bytes() for p in source.rglob('*') if p.is_file()}
    path=info.input_path+'/calc.py'
    def call(name: str,**args: Any) -> AIMessage:
        return AIMessage(content='',tool_calls=[{'id':'c','name':name,'args':args}])
    model=MagicMock();model.bind_tools.return_value.invoke.side_effect=[
        call('run_pytest',file_path=info.input_path+'/tests'),call('read_file',file_path=path),
        call('replace_text',file_path=path,old_text='a-b',new_text='a+b'),
        AIMessage(content='Done'),AIMessage(content='Done'),
    ]
    seen=[]
    answer=LocalAgent(model).run('Fix code and run tests',tools=file_tools.create_file_tools('a',approve=lambda p:seen.append(p) or True))
    assert '1 failed' in answer and '1 passed' in answer and 'pytest завершился успешно' in answer
    assert len(seen)==1 and 'a+b' in (root/info.result_path/'calc.py').read_text()
    assert all((source/name).read_bytes()==raw and (root/info.input_path/name).read_bytes()==raw for name,raw in before.items())
