"""Synthetic PDFs test provenance, completeness accounting and honest coverage."""
from __future__ import annotations

from dataclasses import replace
import hashlib
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

import standards_library as library
from standards_library import Page, Source
from standards_coverage import build_report
from standards_tools import create_standards_tools


@pytest.fixture
def edition(tmp_path: Path) -> tuple[Source, Path, Path, Path]:
    writer = PdfWriter()
    page = writer.add_blank_page(width=600,height=800)
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
        NameObject('/F1'): DictionaryObject({NameObject('/Type'):NameObject('/Font'),
            NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 30 750 Td (4.1 Keep exact source.) Tj 0 -30 Td (4.2 Read exceptions.) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(stream)
    writer.add_blank_page(width=600,height=800)  # A visual-only/blank page is not dropped.
    output=BytesIO();writer.write(output);raw=output.getvalue()
    pdf=tmp_path/'original.pdf';pdf.write_bytes(raw)
    reader=PdfReader(BytesIO(raw))
    pages=tuple(Page(number=i,text=p.extract_text(extraction_mode='layout') or '') for i,p in enumerate(reader.pages,1))
    source=Source(source_id='synthetic',designation='Synthetic standard',title='Test evidence',edition='Fixture v1',
                  sha256=hashlib.sha256(raw).hexdigest(),text_sha256=library.pages_hash(pages),pdf_pages=2,scope='Tests only')
    catalog=tmp_path/'library.json';catalog.write_text(json.dumps({'schema_version':1,'sources':[source.model_dump()]}))
    return source,pdf,tmp_path/'private',catalog


def test_complete_source_is_immutable_and_units_cover_every_page(edition: tuple[Source,Path,Path,Path]) -> None:
    source,pdf,root,_=edition;original=pdf.read_bytes()
    corpus=library.ingest(source,pdf,root)
    assert pdf.read_bytes()==original==(root/source.sha256/'source.pdf').read_bytes()
    assert len(corpus.pages)==2 and not corpus.semantic_review_complete and not corpus.visual_review_complete
    for page in corpus.pages:
        units=[u for u in corpus.units if u.page==page.number]
        assert ''.join(u.text for u in units)==page.text
        assert units[0].start==0 and units[-1].end==len(page.text)
    assert library.ingest(source,pdf,root)==corpus
    assert not list(root.glob('.intake-*'))


def test_search_is_scoped_literal_bounded_and_cites_exact_page(edition: tuple[Source,Path,Path,Path]) -> None:
    source,pdf,root,_=edition;library.ingest(source,pdf,root)
    hits=library.search(source,'Keep  exact',root)
    assert len(hits)==1 and hits[0].page==1 and hits[0].sha256==source.sha256
    assert hits[0].clause_candidate=='4.1'
    assert not library.search(source,'Keep.*exact',root)
    page=library.read_page(source,1,root,limit=8)
    assert source.sha256 in page and 'не полностью' in page
    with pytest.raises(ValueError): library.search(source,'',root)
    with pytest.raises(ValueError): library.search(source,'text',root,limit=11)
    with pytest.raises(ValueError): library.read_page(source,3,root)


@pytest.mark.parametrize('part',['source.pdf','catalog.json'])
def test_corruption_never_becomes_a_new_edition_or_passing_report(
    edition: tuple[Source,Path,Path,Path],part: str,
) -> None:
    source,pdf,root,_=edition;library.ingest(source,pdf,root)
    path=root/source.sha256/part
    if part=='source.pdf': path.write_bytes(b'changed')
    else:
        value=json.loads(path.read_text());value['pages'][0]['text']='invented requirements'
        path.write_text(json.dumps(value))
    with pytest.raises(ValueError): library.load(source,root)
    with pytest.raises(ValueError): library.ingest(source,pdf,root)


def test_mismatched_source_and_symlinks_cannot_publish(edition: tuple[Source,Path,Path,Path]) -> None:
    source,pdf,root,_=edition
    with pytest.raises(ValueError): library.ingest(source.model_copy(update={'sha256':'0'*64}),pdf,root)
    assert not root.exists()
    link=pdf.with_name('link.pdf');link.symlink_to(pdf)
    with pytest.raises(ValueError): library.ingest(source,link,root)
    library.ingest(source,pdf,root)
    stored=root/source.sha256/'source.pdf';stored.unlink();stored.symlink_to(pdf)
    with pytest.raises(ValueError): library.load(source,root)


def test_unknown_or_duplicate_catalog_entries_are_not_silently_selected(edition: tuple[Source,Path,Path,Path]) -> None:
    source,_,_,catalog=edition
    with pytest.raises(ValueError): library.select('../synthetic',catalog)
    catalog.write_text(json.dumps({'schema_version':1,'sources':[source.model_dump(),source.model_dump()]}))
    with pytest.raises(ValueError): library.sources(catalog)


def test_new_section_does_not_inherit_contents_clause_number() -> None:
    text='5.7 Layout schemes\n1 Scope\nThis applies to electric schemes.\n2 References\nOther documents.'
    units=library._units((Page(number=1,text=text),))
    scope=next(u for u in units if 'This applies' in u.text)
    assert scope.clause_candidate=='1' and 'References' not in scope.text
    assert ''.join(u.text for u in units)==text


def test_incomplete_archive_is_corruption_not_an_absent_source(edition: tuple[Source,Path,Path,Path]) -> None:
    source,pdf,root,_=edition;library.ingest(source,pdf,root)
    (root/source.sha256/'catalog.json').unlink()
    with pytest.raises(ValueError,match='Неполная'): library.load(source,root)


def test_coverage_does_not_equate_recipe_or_missing_sources_with_compliance(tmp_path: Path) -> None:
    report=build_report(b'exact candidate bytes','technical_specifications',tmp_path/'empty')
    assert len(report.sources)==len(library.sources()) and len(report.requirements)==39
    assert all(not s.archived for s in report.sources)
    assert sum(r.in_formatting_recipe for r in report.requirements)==22
    assert not report.full_conformance_checked and not report.semantic_catalog_complete
    assert {r.status for r in report.requirements}=={'нужна проверка человеком','проверка не реализована'}
    assert any('2.114' in message for message in report.blockers)
    assert report.candidate_sha256!=build_report(b'different','technical_specifications',tmp_path/'empty').candidate_sha256
    assert 'Процент соответствия не вычисляется' in report.render()
    with pytest.raises(ValueError): build_report(b'candidate','guessed passport')


def test_tu_source_presence_is_distinct_from_implemented_checks(
    edition: tuple[Source,Path,Path,Path],tmp_path: Path,
) -> None:
    import shutil
    source,pdf,root,_=edition
    standards=tmp_path/'standards'
    shutil.copytree(Path(__file__).resolve().parents[1]/'standards',standards)
    metadata=json.loads((standards/'library.json').read_text())
    synthetic_tu=source.model_copy(update={'source_id':'gost-2-114-2016','designation':'ГОСТ 2.114-2016'})
    metadata['sources']=[s for s in metadata['sources'] if s['source_id']!=synthetic_tu.source_id]
    metadata['sources'].append(synthetic_tu.model_dump())
    (standards/'library.json').write_text(json.dumps(metadata))
    missing=build_report(b'candidate','technical_specifications',root,standards)
    assert any('Нет проверенной локальной копии ГОСТ 2.114' in b for b in missing.blockers)
    library.ingest(synthetic_tu,pdf,root)
    present=build_report(b'candidate','technical_specifications',root,standards)
    assert any('Полный источник ГОСТ 2.114-2016' in b and 'не реализована' in b for b in present.blockers)
    assert not any('Нет проверенной локальной копии ГОСТ 2.114' in b for b in present.blockers)
    assert not present.full_conformance_checked and not present.semantic_catalog_complete
    assert {r.status for r in missing.requirements}=={r.status for r in present.requirements}
    (root/synthetic_tu.sha256/'source.pdf').write_bytes(b'changed')
    with pytest.raises(ValueError): build_report(b'candidate','technical_specifications',root,standards)


def test_edition_notice_does_not_silently_substitute_operating_document_standard(tmp_path: Path) -> None:
    report=build_report(b'candidate','unconfirmed',tmp_path/'empty')
    old=next(s for s in report.sources if s.source_id=='gost-2-601-2013')
    assert 'ГОСТ Р 2.601-2019' in old.note and 'не разрешена' in old.note
    assert not old.selected_for_formatting and not old.archived


def test_standards_after_first_page_are_discoverable_without_guessing(tmp_path: Path) -> None:
    tools={t.name:t for t in create_standards_tools([],root=tmp_path/'empty')}
    first=json.loads(tools['list_standards'].invoke({'limit':10}).split('\n',1)[1])
    second=json.loads(tools['list_standards'].invoke({'offset':10,'limit':10}).split('\n',1)[1])
    records=first+second
    assert len(records)==len(library.sources())
    assert len({s['source_id'] for s in records})==len(records)
    assert any(s['source_id']=='gost-2-114-2016' for s in second)


def test_tools_bind_selected_edition_citations_and_cancellation(edition: tuple[Source,Path,Path,Path]) -> None:
    source,pdf,root,catalog=edition;library.ingest(source,pdf,root)
    found: list[str]=[];cancel={'cancelled':False}
    tools={t.name:t for t in create_standards_tools(found,cancel,root,catalog)}
    assert 'synthetic' in tools['list_standards'].invoke({})
    assert not found
    text=tools['search_standard'].invoke({'source_id':'synthetic','query':'Keep exact'})
    assert source.sha256 in text and source.sha256 in found[0] and 'PDF стр. 1' in found[0]
    with pytest.raises(ValueError): tools['read_standard_page'].invoke({'source_id':'guessed','page':1})
    cancel['cancelled']=True
    with pytest.raises(RuntimeError): tools['read_standard_page'].invoke({'source_id':'synthetic','page':1})


def test_document_approval_gets_exact_candidate_coverage_and_does_not_publish_on_rejection(
    tmp_path: Path,monkeypatch: pytest.MonkeyPatch,
) -> None:
    import document_jobs
    import file_tools
    from test_gost_documents import source_docx,candidate
    original=tmp_path/'document.docx';raw=source_docx(original)
    monkeypatch.setattr(file_tools,'WORKSPACE',tmp_path/'chats')
    monkeypatch.setattr(document_jobs,'prepare_document',lambda *a:candidate(raw))
    monkeypatch.setattr(document_jobs,'build_report',lambda data,kind,**kwargs:build_report(data,kind,tmp_path/'library',**kwargs))
    def reject(proposal: document_jobs.DocumentProposal) -> bool:
        assert proposal.coverage is not None
        assert proposal.coverage.document_kind=='technical_specifications'
        assert proposal.coverage.candidate_sha256==hashlib.sha256(proposal.candidate.docx).hexdigest()
        assert '2.114' in proposal.description()
        return False
    outcome=document_jobs.create_document('synthetic',{'path':str(original)},reject,document_kind='technical_specifications')
    assert outcome.receipt is None and not file_tools.output_files('synthetic')
    assert original.read_bytes()==raw


def test_gost_type_selection_rejects_stale_chat_and_passes_explicit_kind() -> None:
    from prilozhenie import AviationRAGApp
    app=AviationRAGApp.__new__(AviationRAGApp)
    app.is_processing=False;app.chat_manager=SimpleNamespace(current_chat_id='a')
    app._pending_attachments=[{'path':'/input/test.docx','name':'test.docx'}]
    app.page=MagicMock();app._handle_send=MagicMock();app._show_toast=MagicMock()
    app._handle_gost_click(None)
    dialog=app.page.open.call_args.args[0]
    dropdown=dialog.content.controls[0];dropdown.value='technical_specifications'
    dialog.actions[1].on_click(None)
    app._handle_send.assert_called_once_with(None,document_name='test.docx',document_kind='technical_specifications',document_form='unconfirmed')
    app._handle_send.reset_mock();app._handle_gost_click(None)
    dialog=app.page.open.call_args.args[0];app.chat_manager.current_chat_id='b'
    dialog.actions[1].on_click(None)
    app._handle_send.assert_not_called()
