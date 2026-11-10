from unittest.mock import MagicMock
import pytest
from langchain_core.messages import AIMessage
from routing import classify


@pytest.mark.parametrize('bad', ['HISTORY_OK', '{"intent":"EXEC"}', '{"intent":"AGENT","extra":1}', '', 'AGENT'])
def test_invalid_output_never_runs_agent(bad: str) -> None:
    model = MagicMock()
    model.bind.return_value.invoke.return_value = AIMessage(content=bad)
    assert classify(model, 'Hello! Reply only HISTORY_OK') == 'CHAT'
    assert classify(model, 'Find my document') == 'SEARCH'


def test_backend_error_read_only_fallback() -> None:
    model = MagicMock()
    model.bind.return_value.invoke.side_effect = TimeoutError()
    assert classify(model, 'Create file') == 'SEARCH'
    assert classify(model, 'Hello') == 'CHAT'


def test_schema_contains_only_three_modes() -> None:
    model = MagicMock()
    model.bind.return_value.invoke.return_value = AIMessage(content='{"intent":"SEARCH"}')
    assert classify(model, 'Manual?') == 'SEARCH'
    schema = model.bind.call_args.kwargs['response_format']['json_schema']['schema']
    assert schema['properties']['intent']['enum'] == ['CHAT', 'SEARCH', 'AGENT']
    assert schema['additionalProperties'] is False


@pytest.mark.parametrize('question', [
    'Как включить излучение шкафа 276ГГ02?',
    'Что такое сигнал PPS?',
    'Как работает шкаф 276ЦЦ02?',
    'Расскажи про плату МКУ',
])
def test_known_equipment_questions_always_search(question: str) -> None:
    model = MagicMock()
    # A valid but wrong model decision used to suppress retrieval entirely.
    model.bind.return_value.invoke.return_value = AIMessage(content='{"intent":"CHAT"}')
    assert classify(model, question) == 'SEARCH'
    model.bind.assert_not_called()


def test_file_action_with_equipment_reference_still_reaches_agent_router() -> None:
    model = MagicMock()
    model.bind.return_value.invoke.return_value = AIMessage(content='{"intent":"AGENT"}')
    assert classify(model, 'Создай файл отчёта по PPS') == 'AGENT'
    model.bind.assert_called_once()


def test_general_chat_is_not_forced_into_document_search() -> None:
    model = MagicMock()
    model.bind.return_value.invoke.return_value = AIMessage(content='{"intent":"CHAT"}')
    assert classify(model, 'Привет, как дела?') == 'CHAT'
