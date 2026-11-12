from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import copy
from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import struct
import tarfile
from typing import Any
from unittest.mock import MagicMock
from zipfile import ZipFile

from docx import Document
from lxml import etree as ET
import pytest

import document_jobs
import document_runner
import file_tools
from document_approval_ui import DocumentApproval
from document_jobs import DocumentProposal, create_document
from document_layout import normalize_stamps
from document_runner import DocumentCandidate, decode_export
from gost_formatter import format_docx
from jobs import RequestJob

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def source_docx(path: Path) -> bytes:
    document = Document()
    document.add_paragraph('Title unchanged')
    document.add_heading('Technical requirements', level=1)
    document.add_paragraph('Technical value: 27.5 V. Do not rewrite.')
    document.add_heading('Numbered requirement is body text', level=3)
    document.add_table(rows=2, cols=2).cell(1, 1).text = '0.001'
    document.sections[0].header.paragraphs[0].text = 'Original stamp and signatures'
    document.save(path)
    return path.read_bytes()


def candidate(raw: bytes) -> DocumentCandidate:
    png = b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + struct.pack('>II', 100, 100)
    return DocumentCandidate(raw, (png,), 'Exact package text', 'Basic GOST profile',
                             ('Formatting prepared',), ('Full compliance is not certified',), False)


def test_format_preserves_text_binary_parts_and_heading3_semantics(tmp_path: Path) -> None:
    source, target = tmp_path/'source.docx', tmp_path/'target.docx'
    before = source_docx(source)
    report = format_docx(source, target)
    assert source.read_bytes() == before
    original, changed = Document(source), Document(target)
    assert [p.text for p in original.paragraphs] == [p.text for p in changed.paragraphs]
    assert changed.paragraphs[1].runs[0].font.size.pt == 16
    assert changed.paragraphs[3].runs[0].font.size is None
    assert not report.full_conformance_checked and report.body_text_preserved
    with ZipFile(source) as a, ZipFile(target) as b:
        assert a.namelist() == b.namelist()
        assert all(a.read(n) == b.read(n) for n in a.namelist()
                   if n not in {'word/document.xml', 'word/settings.xml'})
    with pytest.raises(ValueError, match='новую копию'):
        format_docx(source, target)


def test_no_known_structure_fails_without_fabricated_document(tmp_path: Path) -> None:
    source, target = tmp_path/'source.docx', tmp_path/'target.docx'
    doc = Document(); doc.add_paragraph('Unclassified technical content'); doc.save(source)
    before = source.read_bytes()
    with pytest.raises(ValueError, match='структуры'):
        format_docx(source, target)
    assert source.read_bytes() == before and not target.exists()


def test_stamp_rotation_keeps_text_and_geometry_and_ignores_ambiguous_counts() -> None:
    xml = '''<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
      xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
      xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
      <wps:wsp><wps:spPr><a:xfrm><a:off x="10" y="20"/>
      <a:ext cx="160560" cy="837000"/></a:xfrm></wps:spPr><wps:txbx>
      <w:txbxContent><w:p><w:r><w:t>Inventory number</w:t></w:r></w:p></w:txbxContent>
      </wps:txbx></wps:wsp></w:hdr>'''
    root = ET.fromstring(xml)
    before = root.xpath('//*[local-name()="xfrm"]')[0]
    geometry = ET.tostring(before)
    assert normalize_stamps(root) == (1, 0, 0)
    assert root.xpath('//w:t/text()', namespaces={'w': W[1:-1]}) == ['Inventory number']
    assert ET.tostring(root.xpath('//*[local-name()="xfrm"]')[0]) == geometry
    assert root.find('.//' + W + 'textDirection').get(W+'val') == 'btLr'
    assert normalize_stamps(root) == (0, 0, 0)


def test_legacy_page_field_reserves_width_for_two_digits() -> None:
    root = ET.fromstring('''<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
      xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
      xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
      xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><wp:anchor><wp:extent cx="88900" cy="219710"/>
      <wps:wsp><wps:spPr><a:xfrm><a:ext cx="88900" cy="219710"/></a:xfrm></wps:spPr>
      <wps:txbx><w:txbxContent><w:p><w:r><w:instrText> PAGE </w:instrText></w:r>
      <w:r><w:t>23</w:t></w:r></w:p></w:txbxContent></wps:txbx></wps:wsp></wp:anchor></w:hdr>''')
    normalize_stamps(root)
    assert root.xpath('//*[local-name()="extent"]/@cx') == ['254000']
    assert root.xpath('//*[local-name()="ext"]/@cx') == ['254000']
    assert root.xpath('//w:t/text()', namespaces={'w': W[1:-1]}) == ['23']


def test_pagination_changes_only_bookmarked_toc_cache_and_page_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from document_layout import refresh_pagination
    import pdfplumber
    path = tmp_path/'document.docx'
    xml = f'''<w:document xmlns:w="{W[1:-1]}"><w:body>
    <w:sdt><w:sdtPr><w:docPartGallery w:val="Table of Contents"/></w:sdtPr><w:sdtContent>
    <w:p><w:hyperlink w:anchor="target"><w:r><w:t>Requirements</w:t><w:tab/><w:t>2</w:t></w:r></w:hyperlink></w:p>
    </w:sdtContent></w:sdt><w:p><w:bookmarkStart w:name="target"/><w:r><w:t>Requirements</w:t></w:r></w:p>
    <w:p><w:r><w:t>27.5 V is unchanged</w:t></w:r></w:p></w:body></w:document>'''
    with ZipFile(path, 'w') as z:
        z.writestr('word/document.xml', xml)
        z.writestr('word/header1.xml', f'<w:hdr xmlns:w="{W[1:-1]}"><w:p><w:r><w:instrText> NUMPAGES </w:instrText></w:r><w:r><w:t>2</w:t></w:r></w:p></w:hdr>')
        z.writestr('word/media/image.bin', b'opaque')
    pages = [MagicMock(chars=[]), MagicMock(chars=[]), MagicMock(chars=[
        {'text': c, 'fontname': 'Serif-Bold'} for c in 'Requirements'])]
    opened = MagicMock(); opened.__enter__.return_value.pages = pages
    monkeypatch.setattr(pdfplumber, 'open', lambda _: opened)
    assert refresh_pagination(path, tmp_path/'preview.pdf') == (1, 0)
    with ZipFile(path) as z:
        assert b'27.5 V is unchanged' in z.read('word/document.xml')
        assert b'<w:t>3</w:t>' in z.read('word/document.xml')
        assert b'<w:t>3</w:t>' in z.read('word/header1.xml')
        assert z.read('word/media/image.bin') == b'opaque'


def export(raw: bytes, overrides: dict[str, bytes] | None = None,
           extra: tarfile.TarInfo | None = None) -> bytes:
    c = candidate(raw)
    files = {'document.docx': raw, 'document.pdf': b'%PDF-1.7\n', 'text.txt': b'Fabricated transcript',
             'page-1.png': c.pages[0], 'report.json': json.dumps({
                 'page_count': 1, 'body_text_preserved': True, 'full_conformance_checked': False,
                 'profile': c.profile, 'changes': c.changes, 'warnings': c.warnings,
                 'runtime_fingerprint': '0'*64}).encode()}
    files.update(overrides or {})
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name); info.size = len(data); tar.addfile(info, io.BytesIO(data))
        if extra is not None:
            tar.addfile(extra)
    return stream.getvalue()


def test_export_revalidates_package_and_uses_actual_text_for_consent(tmp_path: Path) -> None:
    raw = source_docx(tmp_path/'input.docx')
    result = decode_export(export(raw))
    assert result.docx == raw and '27.5 V' in result.text
    assert 'Fabricated transcript' not in result.text
    evil = tarfile.TarInfo('../outside'); evil.type = tarfile.SYMTYPE; evil.linkname = '/etc/passwd'
    with pytest.raises(ValueError, match='Недопустимый'):
        decode_export(export(raw, extra=evil))
    huge = b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + struct.pack('>II', 50000, 100)
    with pytest.raises(ValueError, match='Слишком большая'):
        decode_export(export(raw, {'page-1.png': huge}))
    with pytest.raises(ValueError, match='DOCX ZIP'):
        decode_export(export(raw, {'document.docx': b'invalid'}))


@pytest.mark.parametrize('decision', ['approve', 'reject', 'cancel', 'input_changed'])
def test_only_exact_approved_bytes_become_visible_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, decision: str,
) -> None:
    original = tmp_path/'original.docx'; raw = source_docx(original)
    monkeypatch.setattr(file_tools, 'WORKSPACE', tmp_path/'chats')
    monkeypatch.setattr(document_jobs, 'prepare_document', lambda *a: candidate(raw))
    flag = {'cancelled': False}
    seen: list[DocumentProposal] = []

    def approve(proposal: DocumentProposal) -> bool:
        seen.append(proposal)
        assert not Path(proposal.path).exists()
        assert 'SHA-256' in proposal.description()
        assert proposal.candidate.docx == raw
        if decision == 'cancel':
            flag['cancelled'] = True
        if decision == 'input_changed':
            (file_tools.workspace_for_chat('a')/'attached'/original.name).write_bytes(b'changed')
        return decision != 'reject'

    if decision in {'cancel', 'input_changed'}:
        with pytest.raises((RuntimeError, ValueError)):
            create_document('a', {'path': str(original)}, approve, flag)
    else:
        outcome = create_document('a', {'path': str(original)}, approve, flag)
        if decision == 'approve':
            assert outcome.receipt is not None and outcome.receipt.still_matches()
            assert Path(outcome.receipt.path).read_bytes() == raw
            assert 'Файлы чата' in outcome.render()
        else:
            assert outcome.receipt is None
    assert original.read_bytes() == raw and len(seen) == 1
    assert len(file_tools.output_files('a')) == (1 if decision == 'approve' else 0)


def test_missing_document_runtime_never_launches_host_converter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path/'source.docx'; raw = source_docx(path)
    def unavailable() -> list[str]:
        raise RuntimeError('Docker unavailable')
    monkeypatch.setattr(document_runner, 'docker_command', unavailable)
    with pytest.raises(RuntimeError, match='Docker unavailable'):
        document_runner.prepare_document(path)
    assert path.read_bytes() == raw


def test_native_preview_requires_acknowledgment_and_current_job(
    tmp_path: Path, page_loop: asyncio.AbstractEventLoop,
) -> None:
    raw = source_docx(tmp_path/'source.docx')
    page = MagicMock(loop=page_loop)
    proposal = DocumentProposal(str(tmp_path/'result.docx'), candidate(raw))
    job = RequestJob('a')
    approval = DocumentApproval(page, job, lambda: True, proposal)
    opened = __import__('threading').Event()
    page.open.side_effect = lambda _: opened.set()
    with ThreadPoolExecutor() as pool:
        result = pool.submit(approval.wait, 'Preview', 3)
        assert opened.wait(2)
        dialog = approval.dialog
        assert dialog is not None and dialog.actions[1].disabled
        # Even a direct invocation cannot approve without acknowledgment.
        dialog.actions[1].on_click(None)
        assert not result.result(timeout=2)
    stale = DocumentApproval(page, RequestJob('old'), lambda: False, proposal)
    assert not stale.wait('Stale', timeout=0.01)


def test_native_preview_allows_one_exact_acknowledged_candidate(
    tmp_path: Path, page_loop: asyncio.AbstractEventLoop,
) -> None:
    raw = source_docx(tmp_path/'source.docx')
    page = MagicMock(loop=page_loop)
    proposal = DocumentProposal(str(tmp_path/'result.docx'), candidate(raw))
    approval = DocumentApproval(page, RequestJob('a'), lambda: True, proposal)
    def confirm(dialog: Any) -> None:
        checkbox = dialog.content.content.controls[-1]
        checkbox.value = True
        checkbox.on_change(MagicMock(control=checkbox))
        assert not dialog.actions[1].disabled
        dialog.actions[1].on_click(None)
    page.open.side_effect = confirm
    with ThreadPoolExecutor() as pool:
        assert pool.submit(approval.wait, 'Preview', 3).result(timeout=4)


def test_desktop_gost_action_captures_one_document_without_changing_agent_switch() -> None:
    from test_activity_ui import desktop
    app = desktop()
    app._handle_send = MagicMock()
    app._show_toast = MagicMock()
    app.agent_mode = False
    app._pending_attachments = [{'name': 'input.doc', 'path': '/explicit/input.doc'}]
    app.gost_button.on_click(None)
    app._handle_send.assert_called_once_with(None, document_name='input.doc')
    assert not app.agent_mode
    app._pending_attachments.append({'name': 'other.docx', 'path': '/explicit/other.docx'})
    app.gost_button.on_click(None)
    assert app._handle_send.call_count == 1 and app._show_toast.called


def test_file_picker_closes_its_owned_dialog_before_attaching_doc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_activity_ui import desktop
    path = tmp_path/'source.doc'; path.write_bytes(b'legacy')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    app = desktop()
    app.page.window.width, app.page.window.height = 1400, 900
    app._select_file = MagicMock()
    app._open_file_browser()
    dialog = app.page.open.call_args.args[0]
    listing = dialog.content.content.controls[3].content
    row = next(item for item in listing.controls if hasattr(item, 'content')
               and hasattr(item.content, 'controls') and item.content.controls[1].value == 'source.doc')
    row.on_click(None)
    app.page.close.assert_called_once_with(dialog)
    app._select_file.assert_called_once_with(str(path), 'source.doc')


@pytest.mark.skipif(os.environ.get('BUTUZ_DOCUMENTS_LIVE') != '1', reason='Requires prepared local document image')
def test_real_local_document_export_is_complete_and_source_unchanged(tmp_path: Path) -> None:
    path = tmp_path/'source.docx'; raw = source_docx(path)
    result = document_runner.prepare_document(path)
    assert path.read_bytes() == raw
    assert result.pages and '27.5 V' in result.text
    assert result.runtime_fingerprint == document_runner.runtime_fingerprint()
    assert result.docx != raw and result.warnings


@pytest.mark.skipif(os.environ.get('BUTUZ_DOCUMENTS_LIVE') != '1', reason='Requires prepared local document image')
def test_real_continuation_has_no_blank_pages_or_orphan_caption(tmp_path: Path) -> None:
    from docx.enum.text import WD_BREAK

    document = Document(); document.add_heading('Requirements', level=1)
    document.add_paragraph('Таблица 1')
    first = document.add_table(rows=2, cols=2)
    first.cell(0,0).text='Наименование'; first.cell(0,1).text='Значение'
    first.cell(1,0).text='Record A'; first.cell(1,1).text='27.5'
    document.add_page_break()
    caption = document.add_paragraph()
    caption.paragraph_format.page_break_before = True
    caption.add_run().add_break(WD_BREAK.PAGE)
    caption.add_run('Продолжение таблицы 1')
    second = document.add_table(rows=2,cols=2)
    second.cell(0,0).text='Наименование'; second.cell(0,1).text='Значение'
    second.cell(1,0).text='Record B'; second.cell(1,1).text='0.001'
    source = tmp_path/'source.docx'; document.save(source); before=source.read_bytes()
    result = document_runner.prepare_document(source)
    assert source.read_bytes() == before
    assert len(result.pages) == 1
    with ZipFile(io.BytesIO(result.docx)) as package:
        tree=ET.fromstring(package.read('word/document.xml'))
        ns={'w':W[1:-1]}
        rows=tree.find('w:body',ns).findall(W+'tbl')[1].findall(W+'tr')
        assert rows[0].xpath('.//w:t/text()',namespaces=ns) == ['Продолжение таблицы 1']
        assert rows[1].find('w:trPr/w:tblHeader',ns).get(W+'val') == '1'
