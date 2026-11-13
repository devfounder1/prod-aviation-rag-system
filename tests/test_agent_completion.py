from __future__ import annotations

import copy
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

import file_tools
from ai_agent import LocalAgent
from agent_delivery import file_delivery_requested
from answer_prompts import wants_brief_answer, needs_detail_retry
from conversation_context import recent_history
from smart_rag import SmartRAG
from config import settings


@pytest.mark.parametrize('query',[
    'Напиши сортировки на питоне и сохрани это в файлы',
    'ты их не сохранил в файлы чата',
    'Сохрани их в «Файлы чата»',
    'Создай a.py и b.py',
    'Не меняй оригинал, сохрани копию в файл',
    'Write the results to a file',
])
def test_saved_artifact_is_an_explicit_delivery_request(query: str) -> None:
    assert file_delivery_requested(query)


@pytest.mark.parametrize('query',[
    'Напиши сортировку на Python',
    'Не создавай файл, просто объясни код',
    'Do not create a file',
    'How to create a file in Python?',
    'How can I save a file in Python?',
    'Объясни фразу «создай файл»',
    'Как write_file сохраняет файлы?',
    'Объясни этот пример:\n```python\n# создай файл\nprint(1)\n```',
    'Что такое PPS по документации?',
    'Напиши пример сортировки\nДоступные копии вложений: attached/example.py',
])
def test_explanations_and_prohibitions_do_not_require_writes(query: str) -> None:
    assert not file_delivery_requested(query)


def test_prose_is_repaired_into_real_files_with_one_approval_each(tmp_path: Path,monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_tools,'WORKSPACE',tmp_path/'work')
    approvals: list[str]=[]
    model=MagicMock()
    model.bind_tools.return_value.invoke.side_effect=[
        AIMessage(content='Сейчас сохраню файлы.\n```python\nprint(1)\n```'),
        AIMessage(content='',tool_calls=[{'name':'write_file','id':str(i),'args':{'file_path':f'{name}.py','content':'print(1)\n'}}
                                        for i,name in enumerate(['bubble_sort','quick_sort','merge_sort'])]),
        AIMessage(content='Всё сохранено в придуманной папке'),
    ]
    result=LocalAgent(model).run('Сохрани три сортировки в файлы',tools=file_tools.create_file_tools(
        'a',approve=lambda preview:approvals.append(preview) or True))
    assert len(approvals)==3
    assert [p.name for p in file_tools.output_files('a')]==['bubble_sort.py','merge_sort.py','quick_sort.py']
    assert all(p.read_text()=='print(1)\n' for p in file_tools.output_files('a'))
    assert not file_tools.output_files('other-chat')
    assert 'придуманной' not in result and result.count('сохранён, запись проверена')==3


def test_persistent_prose_cannot_be_presented_as_success(tmp_path: Path,monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_tools,'WORKSPACE',tmp_path/'work')
    model=MagicMock(); model.bind_tools.return_value.invoke.return_value=AIMessage(content='Файлы успешно сохранены!')
    result=LocalAgent(model).run('Создай файлы с сортировками',tools=file_tools.create_file_tools('a'))
    assert model.bind_tools.return_value.invoke.call_count==3
    assert 'Файл не сохранён' in result and 'успешно сохранены' not in result
    assert not file_tools.output_files('a')


def test_cancel_during_delivery_repair_never_opens_approval(tmp_path: Path,monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_tools,'WORKSPACE',tmp_path/'work');cancel={'cancelled':False};approve=MagicMock(return_value=True)
    model=MagicMock()
    def prose(*args: object,**kwargs: object) -> AIMessage:
        cancel['cancelled']=True
        return AIMessage(content='Сейчас сохраню')
    model.bind_tools.return_value.invoke.side_effect=prose
    result=LocalAgent(model).run('Создай файл',tools=file_tools.create_file_tools('a',approve=approve,cancel=cancel),cancel_flag=cancel)
    assert result=='Выполнение отменено.' and not approve.called


def test_history_budget_keeps_latest_code_without_changing_stored_history() -> None:
    history=[{'role':'assistant','content':'Unrelated old material '*500},
             {'role':'user','content':'Сохрани код'},
             {'role':'assistant','content':'```python\ndef bubble_sort(values):\n    return sorted(values)\n```'}]
    original=copy.deepcopy(history);limited=recent_history(history)
    assert limited==history[-2:] and history==original
    oversized=recent_history([{'role':'assistant','content':'x'*10000}])
    assert len(oversized[0]['content'])<=3000 and 'не полный исходный код' in oversized[0]['content']


@pytest.mark.parametrize(('query','brief'),[
    ('Расскажи кратко',True),('Explain briefly',True),('В двух словах, что это?',True),
    ('Объясни, но не кратко',False),('Not brief, explain all details',False),
])
def test_brevity_is_only_taken_from_current_request(query: str,brief: bool) -> None:
    assert wants_brief_answer(query) is brief


def test_agent_switch_keeps_scoped_document_search_and_detailed_policy() -> None:
    rag=SmartRAG();rag.search_documents=MagicMock(return_value=('[Источник: manual.txt]\nActual source facts',['manual.txt']))
    model=MagicMock();model.bind_tools.return_value.invoke.return_value=AIMessage(content='Source-based explanation')
    rag.code_agent=LocalAgent(model)
    answer,sources=rag.query_stream('Что такое сигнал PPS?',chat_id='a',agent_mode=True)
    rag.search_documents.assert_called_once_with('Что такое сигнал PPS?','a')
    assert sources==['manual.txt'] and answer=='Source-based explanation'
    messages=model.bind_tools.return_value.invoke.call_args.args[0]
    assert any('РАЗВЁРНУТЫЙ' in str(m.content) for m in messages)
    assert any('Actual source facts' in str(m.content) for m in messages)
    assert model.bind_tools.return_value.invoke.call_args.kwargs['max_tokens']==settings.document_answer_max_tokens


def test_search_repairs_short_explanation_once_without_retrieval_or_history_duplication() -> None:
    context='[Источник: manual.txt]\n'+'Подтверждённые сведения об устройстве. '*120
    rag=SmartRAG();rag.route=MagicMock(return_value='SEARCH');rag.search_documents=MagicMock(return_value=(context,['manual.txt']))
    rag.llm=MagicMock();rag.llm.stream.side_effect=[[AIMessageChunk(content='Краткая справка.')],
                                                  [AIMessageChunk(content='Развёрнутое объяснение с условиями.')]]
    streamed=[]
    answer,sources=rag.query_stream('Как работает устройство?',on_token=streamed.append)
    assert answer==streamed[-1]=='Развёрнутое объяснение с условиями.' and sources==['manual.txt']
    assert rag.llm.stream.call_count==2 and rag.search_documents.call_count==1
    assert rag.llm.stream.call_args.kwargs['max_tokens']==settings.document_answer_max_tokens


def test_short_document_answer_is_allowed_for_small_evidence_or_explicit_brevity() -> None:
    assert not needs_detail_retry('Что такое PPS?','Короткий ответ.','Только один подтверждённый факт.')
    assert not needs_detail_retry('Кратко объясни PPS','Короткий ответ.','Сведения '*500)
    assert not needs_detail_retry('Какова частота сигнала?','1 Гц.','Сведения '*500)


def test_agent_search_tool_also_enables_document_answer_policy() -> None:
    from langchain_core.tools import tool
    @tool
    def search_documents(query: str) -> str:
        """Return synthetic document evidence."""
        return '[Источник: manual.txt]\n'+'Подтверждённые сведения об устройстве. '*120
    model=MagicMock();model.bind_tools.return_value.invoke.side_effect=[
        AIMessage(content='',tool_calls=[{'name':'search_documents','id':'s','args':{'query':'device'}}]),
        AIMessage(content='Коротко.'),AIMessage(content='Подробное объяснение из источника.'),
    ]
    answer=LocalAgent(model).run('Объясни устройство',tools=[search_documents])
    assert answer=='Подробное объяснение из источника.'
    assert model.bind_tools.return_value.invoke.call_count==3
    assert model.bind_tools.return_value.invoke.call_args.kwargs['max_tokens']==settings.document_answer_max_tokens


def test_agent_document_review_has_sources_but_no_write_tools() -> None:
    model=MagicMock();draft='Draft factual explanation. '*30
    model.bind_tools.return_value.invoke.return_value=AIMessage(content=draft)
    model.invoke.return_value=AIMessage(content='Corrected source-based explanation.')
    answer=LocalAgent(model).run('Сравни документацию',tools=[],context='Source evidence. '*100,document_answer=True)
    assert answer=='Corrected source-based explanation.'
    messages=model.invoke.call_args.args[0]
    assert 'UNTRUSTED SOURCE DATA' in messages[1].content and draft in messages[2].content
    assert 'tools' not in model.invoke.call_args.kwargs


def test_failed_search_review_preserves_completed_answer() -> None:
    draft='Source-based draft. '*40
    rag=SmartRAG();rag.route=MagicMock(return_value='SEARCH')
    rag.search_documents=MagicMock(return_value=('[Источник: manual.txt]\n'+'Source evidence. '*100,['manual.txt']))
    rag.llm=MagicMock();rag.llm.stream.side_effect=[[AIMessageChunk(content=draft)],TimeoutError()]
    streamed=[]
    answer,sources=rag.query_stream('Сравни документацию',on_token=streamed.append)
    assert answer==streamed[-1]==draft and sources==['manual.txt']


def test_agent_document_answer_has_at_most_one_extra_text_pass() -> None:
    model=MagicMock();expanded='Подробное объяснение из документа. '*60
    model.bind_tools.return_value.invoke.side_effect=[AIMessage(content='Кратко.'),AIMessage(content=expanded)]
    result=LocalAgent(model).run('Объясни устройство',context='Подтверждённые сведения. '*200,document_answer=True)
    assert result==expanded and model.bind_tools.return_value.invoke.call_count==2
    model.invoke.assert_not_called()
