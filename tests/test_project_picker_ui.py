"""The real folder modal must open, retry invalid paths and release ownership."""
import asyncio
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from project_picker_ui import ProjectFolderBrowser
from ui_dispatch import UiDispatcher


def test_visible_modal_retries_invalid_path_cancels_and_reopens(
    tmp_path: Path, page_loop: asyncio.AbstractEventLoop,
) -> None:
    page = MagicMock(loop=page_loop)
    choose = MagicMock()
    browser = ProjectFolderBrowser(page, lambda: 'a', choose, UiDispatcher(page))

    async def exercise() -> None:
        browser.open()
        while browser.dialog is None:
            await asyncio.sleep(0.01)
        dialog = browser.dialog
        page.open.assert_called_with(dialog)
        field = dialog.content.content.controls[1].controls[1]
        status = dialog.content.content.controls[3]
        field.value = str(tmp_path / 'missing')
        await dialog.actions[1].on_click(None)
        assert 'не выбрана' in status.value and not choose.called
        dialog.actions[0].on_click(None)
        assert browser.session is None
        browser.open()
        while browser.dialog is None:
            await asyncio.sleep(0.01)
        second = browser.dialog
        assert second is not dialog
        # A late dismissal from the previous window cannot cancel the new one.
        dialog.on_dismiss(None)
        assert browser.dialog is second
        second.content.content.controls[1].controls[1].value = str(tmp_path)
        await second.actions[1].on_click(None)
        choose.assert_called_once_with('a', tmp_path.resolve())
        assert browser.session is None

    asyncio.run_coroutine_threadsafe(exercise(), page_loop).result(timeout=5)


@pytest.mark.parametrize('value', ['', '  ', 'relative-project'])
def test_missing_or_relative_path_does_not_select_application_directory(value: str) -> None:
    from project_picker_ui import folder_entries
    with pytest.raises(ValueError, match='полный путь'):
        folder_entries(value)


def test_folder_listing_does_not_block_ui_and_late_results_are_ignored(
    tmp_path: Path, page_loop: asyncio.AbstractEventLoop,
) -> None:
    from project_picker_ui import folder_entries
    (tmp_path / 'src').mkdir()
    (tmp_path / '.git').mkdir()
    (tmp_path / 'file.py').write_text('')
    path, directories, truncated = folder_entries(str(tmp_path))
    assert path == tmp_path.resolve() and [p.name for p in directories] == ['src'] and not truncated
    page = MagicMock(loop=page_loop)
    choose = MagicMock()
    chat = ['a']
    browser = ProjectFolderBrowser(page, lambda: chat[0], choose, UiDispatcher(page))

    async def exercise() -> None:
        browser.open()
        while browser.dialog is None:
            await asyncio.sleep(0.01)
        dialog = browser.dialog
        dialog.content.content.controls[1].controls[1].value = str(tmp_path)
        chat[0] = 'b'
        await dialog.actions[1].on_click(None)
        assert not choose.called
        browser.cancel()
        assert browser.session is None

    asyncio.run_coroutine_threadsafe(exercise(), page_loop).result(timeout=5)
