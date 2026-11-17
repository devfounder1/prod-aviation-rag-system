from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, AIMessageChunk

from activity import ActivityEvent
from ai_agent import LocalAgent
from jobs import JobController
from smart_rag import SmartRAG
from ui_components import ASSETS, PALETTE, ActivityView


def desktop() -> Any:
    from prilozhenie import AviationRAGApp
    app = AviationRAGApp.__new__(AviationRAGApp)
    app.page = MagicMock()
    app.page.loop.is_closed.return_value = False
    app.page.loop.is_running.return_value = True
    app.assets = {key: str(ASSETS / path) for key, path in {
        'icon': 'icon.png', 'assistant': 'avatars/assistant.png', 'user': 'avatars/user.png',
    }.items()}
    app.theme = PALETTE
    app.current_model_display = 'qwen2.5:14b'
    app.is_processing = False
    app._jobs = JobController()
    app.chat_manager = SimpleNamespace(current_chat_id='a', get_current_chat=lambda: {'messages': []})
    app._build_ui()
    app.messages_column.scroll_to = MagicMock()
    return app


def test_search_progress_matches_real_work_without_polluting_response() -> None:
    rag = SmartRAG()
    rag.route = MagicMock(return_value='SEARCH')
    events: list[ActivityEvent] = []
    tokens: list[str] = []
    def search(question: str, chat: str) -> tuple[str, list[str]]:
        assert events[-1] == ActivityEvent('searching', route='SEARCH')
        return '[Источник: manual.txt] Fact', ['manual.txt']
    rag.search_documents = search
    rag.llm = MagicMock()
    def stream(*args: Any, **kwargs: Any) -> Any:
        assert events[-1].phase == 'thinking'
        yield AIMessageChunk(content='Ответ')
        yield AIMessageChunk(content=' по документу')
    rag.llm.stream.side_effect = stream
    answer, _ = rag.query_stream('Вопрос по документу', on_activity=events.append, on_token=tokens.append)
    assert answer == 'Ответ по документу'
    assert tokens == ['Ответ', 'Ответ по документу']
    assert [event.phase for event in events] == ['queued', 'thinking', 'searching', 'thinking', 'answering']


def test_agent_reports_file_work_separately_from_answer(tmp_path: Path, monkeypatch: Any) -> None:
    import file_tools
    monkeypatch.setattr(file_tools, 'WORKSPACE', tmp_path / 'work')
    events: list[ActivityEvent] = []
    tokens: list[str] = []
    rag = SmartRAG()
    model = MagicMock()
    model.bind_tools.return_value.invoke.side_effect = [
        AIMessage(content='', tool_calls=[{'name': 'write_file', 'id': '1',
                                          'args': {'file_path': 'hello.txt', 'content': 'Привет'}}]),
        AIMessage(content='Файл готов'),
    ]
    rag.code_agent = LocalAgent(model)
    def approve(_: str) -> bool:
        assert events[-1].detail == 'Готовлю файл'
        return True
    answer = rag.query_stream('Создай файл', chat_id='a', agent_mode=True, approve=approve,
                              on_activity=events.append, on_token=tokens.append)[0]
    assert 'hello.txt' in answer and 'сохранён, запись проверена' in answer
    assert not tokens  # Progress must never become assistant answer/history text.
    assert 'working' in [event.phase for event in events]
    assert (file_tools.workspace_for_chat('a') / 'hello.txt').read_text() == 'Привет'


def test_empty_chat_has_working_examples_and_mascot() -> None:
    app = desktop()
    app._load_current_chat()
    assert app.welcome.visible and not app.messages_column.visible
    app._send_example = MagicMock()
    controls = app.welcome.content.controls
    assert Path(controls[0].content.src).is_file()
    cards = controls[4].controls
    for card, mode in zip(cards, ['CHAT', 'SEARCH', 'AGENT']):
        card.on_click(None)
        assert app.agent_checkbox.value is (mode == 'AGENT')
        app._send_example.assert_called()
    app.agent_label.on_click(None)
    assert not app.agent_mode and not app.agent_checkbox.value
    assert app.send_button.tooltip == 'Отправить сообщение'
    assert not app.stop_button.visible


def test_approval_is_quiet_and_completion_stops_native_animation() -> None:
    app = desktop()
    app.is_processing = True
    app._add_streaming_placeholder()
    app._set_activity(ActivityEvent('searching', route='SEARCH'))
    assert app.activity.spinner.visible and app._progress_ring.visible
    assert app.send_button.disabled and app.stop_button.visible
    app._set_activity(ActivityEvent('approval', route='AGENT'))
    assert app.activity.text.value == 'Жду подтверждения'
    assert not app.activity.spinner.visible and not app._progress_ring.visible
    app.is_processing = False
    app._set_activity(ActivityEvent('ready'))
    assert not app.activity.spinner.visible
    assert not app.send_button.disabled and not app.stop_button.visible


def test_late_phase_from_old_job_cannot_change_current_chat() -> None:
    app = desktop()
    queued: list[Any] = []
    app.page.loop.call_soon_threadsafe.side_effect = lambda handler: queued.append(handler)
    job = app._jobs.start('a')
    app._queue_activity(job, ActivityEvent('searching', route='SEARCH'))
    app.chat_manager.current_chat_id = 'b'
    app._jobs.start('b')
    queued[0]()
    assert app.activity.event.phase == 'ready'


def test_approval_and_cancel_are_job_scoped() -> None:
    app = desktop()
    app._queue_activity = MagicMock()
    app._show_file_approval_dialog = MagicMock(return_value=True)
    job = app._jobs.start('a')
    assert app._approve_for_job(job, 'Exact change')
    assert [call.args[1].phase for call in app._queue_activity.call_args_list] == ['approval', 'working']
    app.is_processing = True
    app._handle_cancel_click(None)
    assert job.token['cancelled']
    assert app.activity.event.phase == 'cancelled'
    assert not app._approve_for_job(job, 'Late change')
    assert app._show_file_approval_dialog.call_count == 1


def test_terminal_and_repeated_phases_do_not_keep_spinning() -> None:
    view = ActivityView()
    for phase in ['error', 'cancelled', 'ready', 'approval']:
        view.apply(ActivityEvent(phase))
        assert not view.spinner.visible
