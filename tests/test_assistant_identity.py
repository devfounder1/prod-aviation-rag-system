from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from ai_agent import LocalAgent
from assistant_identity import ASSISTANT_CREATOR, ASSISTANT_NAME, IDENTITY_PROMPT, identity_reply
from smart_rag import SmartRAG


@pytest.mark.parametrize('agent_mode', [False, True])
@pytest.mark.parametrize('question,expected', [
    ('слушай, а как тебя вообще зовут ?', ASSISTANT_NAME),
    ('Привет! Как тебя зовут?', ASSISTANT_NAME),
    ('Представься', ASSISTANT_NAME),
    ('What is your name?', ASSISTANT_NAME),
    ('Кто твой создатель?', ASSISTANT_CREATOR),
    ('Кто тебя создал?', ASSISTANT_CREATOR),
    ('Как зовут твоего создателя?', ASSISTANT_CREATOR),
])
def test_identity_is_exact_despite_old_history_and_agent_switch(
    question: str, expected: str, agent_mode: bool,
) -> None:
    rag = SmartRAG()
    rag.route = MagicMock(side_effect=AssertionError('Identity does not need model routing'))
    rag._agent_tools = MagicMock(side_effect=AssertionError('Identity must not run tools'))
    rag.search_documents = MagicMock(side_effect=AssertionError('Identity must not search private documents'))
    streamed: list[str] = []
    history: list[dict[str, Any]] = [{'role': 'assistant', 'content': 'Меня зовут Qwen. Мой создатель — Alibaba.'}]
    assert rag.query_stream(question, chat_history=history, agent_mode=agent_mode,
                            on_token=streamed.append) == (expected, [])
    assert streamed == [expected]


@pytest.mark.parametrize('question', [
    'Создай файл name.txt с текстом «Как тебя зовут?»',
    'Как зовут создателя Python?',
    'Кто создал Qwen?',
    'Найди в документах, кто создатель шкафа',
    'Как тебя зовут и создай файл с ответом',
    'Переведи на английский: «Кто твой создатель?»',
])
def test_identity_does_not_replace_document_or_file_tasks(question: str) -> None:
    assert identity_reply(question) is None


@pytest.mark.parametrize('intent', ['CHAT', 'SEARCH', 'AGENT'])
def test_combined_tasks_keep_identity_in_every_system_prompt(intent: str) -> None:
    rag = SmartRAG()
    rag.route = MagicMock(return_value=intent)
    rag.llm = MagicMock()
    rag.llm.stream.return_value = [AIMessageChunk(content='Ответ')]
    rag.code_agent = LocalAgent(rag.llm)
    rag.llm.bind_tools.return_value.invoke.return_value = AIMessage(content='Ответ')
    rag._agent_tools = MagicMock(return_value=[])
    rag.search_documents = MagicMock(return_value=('Документ с данными', ['manual.txt']))
    rag.query_stream('Назови своё имя и объясни назначение помощника')
    call = (rag.llm.bind_tools.return_value.invoke.call_args if intent == 'AGENT'
            else rag.llm.stream.call_args)
    assert IDENTITY_PROMPT in call.args[0][0].content


def test_cancelled_request_cannot_emit_identity() -> None:
    assert SmartRAG().query_stream('Как тебя зовут?', cancel_flag={'cancelled': True}) == ('Выполнение отменено.', [])
    model = MagicMock()
    assert LocalAgent(model).run('Кто тебя создал?') == ASSISTANT_CREATOR
    model.bind_tools.assert_not_called()
