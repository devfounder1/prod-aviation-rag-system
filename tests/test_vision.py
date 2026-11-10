import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from ai_agent import LocalAgent
from config import settings
from jobs import CancelToken, JobController
from llm_client import create_llm
from smart_rag import SmartRAG
from vision import UnsupportedImageModelError, VisionAnalysisError, prefer_image_chat


@pytest.fixture
def picture(tmp_path: Path) -> Path:
    image = tmp_path / 'icon.png'
    image.write_bytes(base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j1ioAAAAASUVORK5CYII='))
    return image


def streamed(model: str, answer: str) -> httpx.Response:
    event = {'id': 'local-image-test', 'object': 'chat.completion.chunk', 'created': 0,
             'model': model, 'choices': [{'index': 0, 'delta': {'content': answer}, 'finish_reason': None}]}
    return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                          text='data: ' + json.dumps(event) + '\n\ndata: [DONE]\n\n')


def use_client(model: object, client: httpx.Client) -> None:
    model.root_client = model.root_client.with_options(http_client=client)
    model.client = model.root_client.chat.completions


def test_image_goes_to_local_vision_then_text_model_without_switching(picture: Path) -> None:
    rag = SmartRAG()
    rag.route = MagicMock(side_effect=AssertionError('Plain image must not invoke router'))
    rag.search_documents = MagicMock(side_effect=AssertionError('No unrelated RAG context'))
    rag.vision._llm = create_llm(settings.vision_model_name)
    calls = []
    def respond(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == 'http://127.0.0.1:11434/v1/chat/completions'
        payload = json.loads(request.content)
        calls.append(payload)
        if payload['model'] == settings.vision_model_name:
            assert payload['messages'][-1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')
            assert payload['max_tokens'] == settings.vision_max_tokens
            assert 'tools' not in payload
            return streamed(payload['model'], 'На картинке красный круг.')
        assert payload['model'] == settings.llm_model_name
        assert 'image_url' not in json.dumps(payload)
        assert any('красный круг' in str(m['content']) and m['role'] == 'user' for m in payload['messages'])
        return streamed(payload['model'], 'На изображении красный круг.')
    tokens = []
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        use_client(rag.llm, client)
        use_client(rag.vision._llm, client)
        answer, sources = rag.query_stream('Что на картинке?', attachments=[{'path': str(picture)}], on_token=tokens.append)
    assert [c['model'] for c in calls] == [settings.vision_model_name, settings.llm_model_name]
    assert rag.model_name == settings.llm_model_name
    assert answer == 'На изображении красный круг.'
    assert sources == [picture.name] and tokens[-1] == answer
    assert any('Анализирую изображение' in token for token in tokens)


@pytest.mark.parametrize('status,message,expected', [
    (400, 'Multimodal data provided, but model does not support multimodal requests.', UnsupportedImageModelError),
    (404, 'model not found', VisionAnalysisError),
])
def test_vision_failure_stops_pipeline_with_actionable_error(picture: Path, status: int,
                                                            message: str, expected: type[Exception]) -> None:
    rag = SmartRAG()
    rag.vision._llm = create_llm(settings.vision_model_name)
    rag.llm = MagicMock()
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={'error': {'message': message, 'type': 'invalid_request_error'}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        use_client(rag.vision._llm, client)
        with pytest.raises(expected, match='VISION_MODEL_NAME') as error:
            rag.query_stream('describe', attachments=[{'path': str(picture)}])
    assert 'переключать не нужно' in str(error.value)
    assert 'base64' not in str(error.value)
    rag.llm.stream.assert_not_called()
    assert rag.last_sources == []


def test_explicitly_selected_vision_model_uses_single_call(picture: Path) -> None:
    rag = SmartRAG(model_name=settings.vision_model_name)
    rag.vision.analyze = MagicMock(side_effect=AssertionError('Must not run twice'))
    calls = []
    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload['model'] == settings.vision_model_name
        assert payload['messages'][-1]['content'][1]['type'] == 'image_url'
        return streamed(payload['model'], 'Иконка.')
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        use_client(rag.llm, client)
        assert rag.query_stream('describe', attachments=[{'path': str(picture)}]) == ('Иконка.', [picture.name])
    assert len(calls) == 1


def test_agent_receives_observations_and_can_keep_using_text_model(picture: Path) -> None:
    model = MagicMock()
    model.bind_tools.return_value.invoke.return_value = AIMessage(content='Summary created')
    rag = SmartRAG()
    rag.vision.analyze = MagicMock(return_value='[Изображение: icon.png]\nКрасный круг')
    rag.code_agent = LocalAgent(model)
    rag._agent_tools = MagicMock(return_value=[])
    answer, sources = rag.query_stream('Save description to file', agent_mode=True, attachments=[{'path': str(picture)}])
    assert answer == 'Summary created' and sources == [picture.name]
    messages = model.bind_tools.return_value.invoke.call_args.args[0]
    assert messages[-2].content == 'Save description to file'
    assert any('Красный круг' in str(m.content) for m in messages)
    assert 'image_url' not in str(messages)


def test_search_keeps_both_visual_observations_and_document_context(picture: Path) -> None:
    rag = SmartRAG()
    rag.vision.analyze = MagicMock(return_value='Visual observation: blue label')
    rag.route = MagicMock(return_value='SEARCH')
    rag.search_documents = MagicMock(return_value=('[Источник: manual.txt]\nBlue label is TEST-A', ['manual.txt']))
    rag.llm = MagicMock()
    rag.llm.stream.return_value = [AIMessageChunk(content='TEST-A')]
    _, sources = rag.query_stream('Сравни с документацией', attachments=[{'path': str(picture)}])
    assert sources == ['manual.txt', picture.name]
    data = str(rag.llm.stream.call_args.args[0])
    assert 'blue label' in data and 'manual.txt' in data
    assert 'image_url' not in data


def test_cancel_during_vision_never_calls_primary_model(picture: Path) -> None:
    token = CancelToken()
    rag = SmartRAG()
    rag.vision._llm = MagicMock()
    def stream(messages: object):
        token['cancelled'] = True
        yield AIMessageChunk(content='partial')
    rag.vision._llm.bind.return_value.stream.side_effect = stream
    rag.llm = MagicMock()
    assert rag.query_stream('describe', attachments=[{'path': str(picture)}], cancel_flag=token) == ('Выполнение отменено.', [])
    rag.llm.stream.assert_not_called()


def test_unrelated_primary_error_is_not_relabelled(picture: Path) -> None:
    rag = SmartRAG()
    rag.vision.analyze = MagicMock(return_value='An icon')
    rag.llm = MagicMock()
    failure = RuntimeError('primary model not found')
    rag.llm.stream.side_effect = failure
    with pytest.raises(RuntimeError, match='primary model not found') as error:
        rag.query_stream('describe', attachments=[{'path': str(picture)}])
    assert error.value is failure


def test_gui_retains_image_for_retry(picture: Path) -> None:
    from prilozhenie import AviationRAGApp
    app = AviationRAGApp.__new__(AviationRAGApp)
    app._jobs = JobController()
    job = app._jobs.start('chat')
    app.chat_manager = SimpleNamespace(current_chat_id='chat')
    app._pending_attachments = [{'path': 'other.png', 'name': 'other.png'}]
    app._update_pending_attachments_display = MagicMock()
    app._finalize_streaming_message = MagicMock()
    image = {'path': str(picture), 'name': picture.name}
    app._fail_job(job, 'Vision unavailable', [image])
    assert app._pending_attachments == [{'path': 'other.png', 'name': 'other.png'}, image]
    assert app._jobs.current is None


def test_explicit_image_document_search_and_actions_keep_routing(picture: Path) -> None:
    attachment = [{'path': str(picture)}]
    assert not prefer_image_chat('Сравни схему с документацией', attachment)
    assert not prefer_image_chat('Create a file describing this image', attachment)
    assert not prefer_image_chat('Explain', attachment + [{'path': 'manual.pdf'}])


def test_empty_visual_analysis_does_not_let_text_model_guess(picture: Path) -> None:
    rag = SmartRAG()
    rag.vision._llm = MagicMock()
    rag.vision._llm.bind.return_value.stream.return_value = []
    rag.llm = MagicMock()
    with pytest.raises(VisionAnalysisError, match='пустое описание'):
        rag.query_stream('describe', attachments=[{'path': str(picture)}])
    rag.llm.stream.assert_not_called()
