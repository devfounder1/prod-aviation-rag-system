from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
import pytest
import file_tools
from jobs import CancelToken


def tools(chat: str, **kwargs: object) -> dict:
    return {t.name: t for t in file_tools.create_file_tools(chat, **kwargs)}


@pytest.fixture(autouse=True)
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_tools, 'WORKSPACE', tmp_path / 'work')


def test_parallel_chats_same_filename_are_isolated() -> None:
    def create(chat: str) -> str:
        t = tools(chat)
        t['write_file'].invoke({'file_path': 'report.txt', 'content': chat})
        return t['read_file'].invoke({'file_path': 'report.txt'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, ['chat-a', 'chat-b']))
    assert results == ['UNTRUSTED FILE DATA:\nchat-a', 'UNTRUSTED FILE DATA:\nchat-b']
    a, b = file_tools.workspace_for_chat('chat-a'), file_tools.workspace_for_chat('chat-b')
    (a / 'escape').symlink_to(b, target_is_directory=True)
    with pytest.raises(ValueError):
        tools('chat-a')['read_file'].invoke({'file_path': 'escape/report.txt'})
    with pytest.raises(ValueError):
        tools('chat-a')['read_file'].invoke({'file_path': '../report.txt'})


def test_original_access_and_approval_are_per_request(tmp_path: Path) -> None:
    original = tmp_path / 'original.txt'
    original.write_text('original')
    a_calls, b_calls = [], []
    a = tools('a', attachments=[{'path': str(original)}],
              approve=lambda text: a_calls.append(text) or True)
    b = tools('b', approve=lambda text: b_calls.append(text) or True)
    args = {'file_name': original.name, 'new_content': 'updated'}
    assert 'not attached' in b['update_attached_file'].invoke(args)
    assert original.read_text() == 'original'
    assert not b_calls
    assert 'after approval' in a['update_attached_file'].invoke(args)
    assert original.read_text() == 'updated'
    assert len(a_calls) == 1
    assert next(tmp_path.glob('*.bak')).read_text() == 'original'
    # Next request in same chat does not inherit original-file permission.
    assert 'not attached' in tools('a')['update_attached_file'].invoke(args)


def test_cancel_during_approval_prevents_write(tmp_path: Path) -> None:
    original = tmp_path / 'file.txt'
    original.write_text('original')
    token = CancelToken()
    def approve(_: str) -> bool:
        token['cancelled'] = True
        return True
    t = tools('a', attachments=[{'path': str(original)}], approve=approve, cancel=token)
    with pytest.raises(RuntimeError):
        t['update_attached_file'].invoke({'file_name': 'file.txt', 'new_content': 'bad'})
    assert original.read_text() == 'original'


def test_external_edit_is_not_overwritten(tmp_path: Path) -> None:
    original = tmp_path / 'file.txt'
    original.write_text('initial')
    t = tools('a', attachments=[{'path': str(original)}], approve=lambda _: True)
    original.write_text('external change')
    assert 'changed since' in t['update_attached_file'].invoke({'file_name': 'file.txt', 'new_content': 'bad'})
    assert original.read_text() == 'external change'


@pytest.mark.parametrize('name,args', [
    ('write_file', {'file_path': 'report.txt', 'content': 'new'}),
    ('append_to_file', {'file_path': 'report.txt', 'text_to_append': 'new'}),
    ('replace_lines', {'file_path': 'report.txt', 'start_line': 1, 'end_line': 1, 'new_content': 'new'}),
])
def test_workspace_mutations_require_one_gui_approval_and_respect_rejection(
    name: str, args: dict[str, Any],
) -> None:
    path = file_tools.workspace_for_chat('a') / 'report.txt'
    path.write_text('before')
    seen = []
    t = tools('a', approve=lambda description: seen.append(description) or False)
    assert 'rejected' in t[name].invoke(args)
    assert path.read_text() == 'before'
    assert len(seen) == 1 and str(path) in seen[0] and 'new' in seen[0]
    # A model retry in the same request must not reopen the rejected action.
    assert 'rejected' in t[name].invoke(args)
    assert len(seen) == 1


def test_new_docx_and_cancelled_creation(tmp_path: Path) -> None:
    from docx import Document
    seen = []
    t = tools('a', approve=lambda description: seen.append(description) or True)
    assert 'Created/updated' in t['write_file'].invoke({'file_path': 'report.docx', 'content': 'Отчёт'})
    path = file_tools.workspace_for_chat('a') / 'report.docx'
    assert Document(path).paragraphs[0].text == 'Отчёт'
    assert len(seen) == 1
    token = CancelToken()
    def cancel(_: str) -> bool:
        token['cancelled'] = True
        return True
    t = tools('b', approve=cancel, cancel=token)
    with pytest.raises(RuntimeError):
        t['write_file'].invoke({'file_path': 'cancelled.txt', 'content': 'bad'})
    assert not (file_tools.workspace_for_chat('b') / 'cancelled.txt').exists()


def test_external_workspace_change_during_modal_is_not_overwritten() -> None:
    path = file_tools.workspace_for_chat('a') / 'report.txt'
    path.write_text('initial')
    def approve(_: str) -> bool:
        path.write_text('external edit')
        return True
    with pytest.raises(ValueError, match='changed while'):
        tools('a', approve=approve)['write_file'].invoke({'file_path': 'report.txt', 'content': 'bad'})
    assert path.read_text() == 'external edit'
