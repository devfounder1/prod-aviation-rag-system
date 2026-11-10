"""Exercise the real Flet dialog callbacks without a native window or model."""
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import file_tools
from agent_files_ui import AgentFilesUI, FileApproval, export_copy
from jobs import RequestJob



@pytest.mark.parametrize('allow', [True, False])
def test_modal_decision_resumes_worker_and_controls_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, allow: bool, page_loop: asyncio.AbstractEventLoop,
) -> None:
    monkeypatch.setattr(file_tools, 'WORKSPACE', tmp_path / 'chats')
    page = MagicMock(loop=page_loop)
    opened = []
    opened_event = threading.Event()
    def open_dialog(dialog: Any) -> None:
        opened.append(dialog)
        opened_event.set()
    page.open.side_effect = open_dialog
    job = RequestJob('a')
    approval = FileApproval(page, job, lambda: True)
    tools = {t.name: t for t in file_tools.create_file_tools('a', approve=approval.wait)}
    target = file_tools.workspace_for_chat('a') / 'hello.txt'
    with ThreadPoolExecutor() as pool:
        future = pool.submit(tools['write_file'].invoke, {'file_path': 'hello.txt', 'content': 'Привет'})
        assert opened_event.wait(timeout=3)
        dialog = opened[0]
        assert not target.exists()
        preview = dialog.content.content.controls[1].content.controls[0].value
        assert str(target) in preview and 'Привет' in preview and 'Создать' in preview
        dialog.actions[1 if allow else 0].on_click(None)
        result = future.result(timeout=3)
    assert target.exists() is allow
    if allow:
        assert target.read_text() == 'Привет'
        assert 'Created/updated' in result
    else:
        assert 'rejected' in result
    asyncio.run_coroutine_threadsafe(asyncio.sleep(0), page_loop).result(timeout=3)
    page.close.assert_called_with(dialog)


def test_cancellation_timeout_and_stale_dialog_cannot_authorize_write(page_loop: asyncio.AbstractEventLoop) -> None:
    page = MagicMock(loop=page_loop)
    job = RequestJob('a')
    approval = FileApproval(page, job, lambda: True)
    page.open.side_effect = lambda _: job.token.__setitem__('cancelled', True)
    assert not approval.wait('Create file', timeout=0.01)
    approval.decide(True)
    assert not approval.approved
    stale = FileApproval(page, RequestJob('b'), lambda: False)
    assert not stale.wait('Old chat', timeout=0.01)
    page.open.side_effect = None
    expired = FileApproval(page, RequestJob('c'), lambda: True)
    assert not expired.wait('No response', timeout=0.001)
    expired.decide(True)
    assert not expired.approved


def test_outputs_export_preserves_bytes_and_hides_attachments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(file_tools, 'WORKSPACE', tmp_path / 'chats')
    root = file_tools.workspace_for_chat('a')
    report = root / 'report.docx'
    report.write_bytes(b'\x00\xffbinary')
    (root / 'attached').mkdir()
    (root / 'attached' / 'private.txt').write_text('private')
    (root / '.agent-temp').write_text('temp')
    other = file_tools.workspace_for_chat('b') / 'other.txt'
    other.write_text('other chat')
    (root / 'escape').symlink_to(other)
    assert file_tools.output_files('a') == [report]
    destination = tmp_path / 'user-chosen.docx'
    export_copy('a', report, destination)
    assert report.read_bytes() == destination.read_bytes() == b'\x00\xffbinary'
    with pytest.raises(ValueError):
        export_copy('a', other, destination)
    with pytest.raises(ValueError):
        export_copy('a', root / 'attached' / 'private.txt', destination)
    with pytest.raises(ValueError):
        export_copy('a', report, Path(__file__).resolve().parent / 'no-export.txt')


def test_save_picker_cancel_and_chat_switch_leave_files_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, page_loop: asyncio.AbstractEventLoop,
) -> None:
    monkeypatch.setattr(file_tools, 'WORKSPACE', tmp_path / 'chats')
    source = file_tools.workspace_for_chat('a') / 'report.txt'
    source.write_text('result')
    current = ['a']
    ui = AgentFilesUI(MagicMock(loop=page_loop), lambda: current[0], MagicMock())
    ui.pending_export = ('a', source)
    ui.save_result(MagicMock(path=None))
    assert ui.pending_export is None
    destination = tmp_path / 'copy.txt'
    ui.pending_export = ('a', source)
    current[0] = 'b'
    ui.save_result(MagicMock(path=str(destination)))
    assert not destination.exists()
    current[0] = 'a'
    ui.pending_export = ('a', source)
    ui.save_result(MagicMock(path=str(destination)))
    assert destination.read_text() == 'result'
