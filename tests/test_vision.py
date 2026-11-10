import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from langchain_core.messages import AIMessage

from ai_agent import LocalAgent
from jobs import JobController
from smart_rag import SmartRAG
from vision import UnsupportedImageModelError


@pytest.fixture
def picture(tmp_path: Path) -> Path:
    image = tmp_path / 'icon.png'
    image.write_bytes(base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j1ioAAAAASUVORK5CYII='))
    return image


def test_text_model_image_error_is_actionable(picture: Path) -> None:
    rag = SmartRAG()
    rag.route = MagicMock(return_value='CHAT')
    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload['model'] == 'qwen2.5:14b'
        assert payload['stream'] is True
        content = payload['messages'][-1]['content']
        assert content[1]['image_url']['url'].startswith('data:image/png;base64,')
        return httpx.Response(400, json={'error': {
            'message': 'Multimodal data provided, but model does not support multimodal requests.',
            'type': 'invalid_request_error'}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        rag.llm.root_client = rag.llm.root_client.with_options(http_client=client)
        rag.llm.client = rag.llm.root_client.chat.completions
        with pytest.raises(UnsupportedImageModelError, match='qwen2.5vl:7b') as error:
            rag.query_stream('Что на картинке?', attachments=[{'path': str(picture)}])
    assert 'qwen2.5:14b' in str(error.value)
    assert 'Настройки' in str(error.value)
    assert 'base64' not in str(error.value)
    assert rag.last_sources == []


def test_vision_stream_and_sources(picture: Path) -> None:
    rag = SmartRAG(model_name='qwen2.5vl:7b')
    rag.route = MagicMock(return_value='CHAT')
    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload['model'] == 'qwen2.5vl:7b'
        events = []
        for content in ('На изображении ', 'иконка.'):
            events.append('data: ' + json.dumps({'id': 'local-vision', 'object': 'chat.completion.chunk',
                'created': 0, 'model': payload['model'], 'choices': [
                {'index': 0, 'delta': {'content': content}, 'finish_reason': None}]}))
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                              text='\n\n'.join(events) + '\n\ndata: [DONE]\n\n')
    tokens = []
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        rag.llm.root_client = rag.llm.root_client.with_options(http_client=client)
        rag.llm.client = rag.llm.root_client.chat.completions
        answer, sources = rag.query_stream('Что изображено?', attachments=[{'path': str(picture)}],
                                           on_token=tokens.append)
    assert answer == 'На изображении иконка.'
    assert sources == [picture.name]
    assert tokens[-1] == answer


def test_unrelated_backend_errors_are_not_relabelled(picture: Path) -> None:
    rag = SmartRAG()
    rag.route = MagicMock(return_value='CHAT')
    rag.llm = MagicMock()
    failure = RuntimeError('model not found')
    rag.llm.stream.side_effect = failure
    with pytest.raises(RuntimeError, match='model not found') as error:
        rag.query_stream('describe', attachments=[{'path': str(picture)}])
    assert error.value is failure


def test_agent_receives_image_instead_of_silently_ignoring_it(picture: Path) -> None:
    model = MagicMock()
    model.bind_tools.return_value.invoke.return_value = AIMessage(content='An icon')
    rag = SmartRAG()
    rag.code_agent = LocalAgent(model)
    rag._agent_tools = MagicMock(return_value=[])
    answer, _ = rag.query_stream('describe', agent_mode=True, attachments=[{'path': str(picture)}])
    assert answer == 'An icon'
    message = model.bind_tools.return_value.invoke.call_args.args[0][-2]
    assert message.content[0]['text'] == 'describe'
    assert message.content[1]['type'] == 'image_url'


def test_gui_retains_image_for_retry_and_finishes_failed_job(picture: Path) -> None:
    from prilozhenie import AviationRAGApp, AVAILABLE_MODELS
    assert 'qwen2.5vl:7b' in AVAILABLE_MODELS.values()
    app = AviationRAGApp.__new__(AviationRAGApp)
    app._jobs = JobController()
    job = app._jobs.start('chat')
    app.chat_manager = SimpleNamespace(current_chat_id='chat')
    app._pending_attachments = [{'path': 'other.png', 'name': 'other.png'}]
    app._update_pending_attachments_display = MagicMock()
    app._finalize_streaming_message = MagicMock()
    image = {'path': str(picture), 'name': picture.name}
    app._fail_job(job, 'Выберите vision-модель', [image])
    assert app._pending_attachments == [{'path': 'other.png', 'name': 'other.png'}, image]
    assert app._jobs.current is None
    app._finalize_streaming_message.assert_called_once_with('Выберите vision-модель', [], 'chat')


def test_plain_image_question_bypasses_router_and_document_search(picture: Path) -> None:
    from langchain_core.messages import AIMessageChunk
    rag = SmartRAG(model_name='qwen2.5vl:7b')
    rag.route = MagicMock(side_effect=AssertionError('Image description must not route to documents'))
    rag.search_documents = MagicMock(side_effect=AssertionError('Must not load unrelated RAG context'))
    rag.llm = MagicMock()
    rag.llm.stream.return_value = [AIMessageChunk(content='Иконка')]
    assert rag.query_stream('Что изображено на картинке?', attachments=[{'path': str(picture)}]) == ('Иконка', [picture.name])


def test_explicit_image_document_search_and_actions_keep_routing(picture: Path) -> None:
    from vision import prefer_image_chat
    attachment = [{'path': str(picture)}]
    assert not prefer_image_chat('Сравни схему с документацией', attachment)
    assert not prefer_image_chat('Create a file describing this image', attachment)
    assert not prefer_image_chat('Explain', attachment + [{'path': 'manual.pdf'}])
