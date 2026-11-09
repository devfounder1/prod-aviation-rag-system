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
