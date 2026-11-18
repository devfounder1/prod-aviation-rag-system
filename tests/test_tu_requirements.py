"""Public synthetic documents; full private source checks are explicit opt-in."""
from __future__ import annotations

from dataclasses import asdict
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from docx import Document
import pytest

from standards_coverage import build_report,_json_default
from standards_library import Page,load,select
from tu_requirements import Catalog,build_review,load_catalog,render_catalog,source_inventory,verify_inventory
from tu_validation import DocumentCheck


def synthetic_doc() -> bytes:
    doc=Document();doc.add_paragraph('Настоящие технические условия распространяются на тестовый узел.')
    doc.add_heading('Технические требования',1);doc.add_paragraph('Сверить с TEST.123456.001 ТУ.')
    out=BytesIO();doc.save(out);return out.getvalue()


def test_catalog_accounts_for_every_numbered_paragraph_and_does_not_create_recipe() -> None:
    c=load_catalog()
    assert len(c.clauses)==88 and len(c.requirements)==148
    assert len({r.id for r in c.requirements})==148
    assert sum(p.kind=='heading' for p in c.clauses)==7
    assert c.clauses[-1].clause=='6.14'
    assert {r.clause for r in c.requirements}=={p.clause for p in c.clauses if p.kind=='requirements'}
    assert len({p for d in c.page_disposition for p in d.pages})==15
    from standard_profiles import load_profile
    assert 'reviews/gost_2_114_2016.json' not in load_profile().selected_files
    assert all(r.automation in {'manual','intro','page-size','references','section-outline','text-profile','figure-layout'} for r in c.requirements)


@pytest.mark.parametrize('tamper',['duplicate','missing_item','heading','unknown_status','wrong_edition','unknown_dependency'])
def test_invalid_or_invented_claims_in_catalog_are_rejected(tamper: str) -> None:
    raw=load_catalog().model_dump(mode='json')
    if tamper=='duplicate':raw['requirements'].append(raw['requirements'][0])
    elif tamper=='missing_item':raw['requirements']=[r for r in raw['requirements'] if r['clause']!='5.7.10']
    elif tamper=='heading':next(c for c in raw['clauses'] if c['clause']=='5.1')['kind']='requirements'
    elif tamper=='unknown_status':raw['requirements'][0]['status']='выполнено'
    elif tamper=='wrong_edition':raw['source_sha256']='0'*64
    else:raw['requirements'][0]['dependencies'].append('Unreviewed substitution')
    with pytest.raises(ValueError):Catalog.model_validate(raw)


def test_mechanical_inventory_hashes_continuations_not_only_number_labels() -> None:
    pages=tuple(Page(number=i,text=('4.1 First paragraph\n' if i==4 else 'Continuation text\n4.2 Next paragraph\n' if i==5 else '')) for i in range(1,16))
    clauses=source_inventory(pages)
    assert [c.clause for c in clauses]==['4.1','4.2']
    assert [s.page for s in clauses[0].spans]==[4,5]
    changed=tuple(p.model_copy(update={'text':p.text.replace('Continuation','Changed')}) if p.number==5 else p for p in pages)
    assert source_inventory(changed)[0].span_sha256!=clauses[0].span_sha256
    with pytest.raises(ValueError):source_inventory(tuple(p for p in pages if p.number!=10))


def test_missing_source_suppresses_candidate_observations_and_all_conformity_claims() -> None:
    raw=synthetic_doc();observation=DocumentCheck('page-size','fixture','измерено','synthetic','A4')
    r=build_review(raw,'print_framed',None,(observation,))
    assert r.candidate_sha256==hashlib.sha256(raw).hexdigest()
    assert not r.inventory_verified and not r.source_available
    assert all(not row.observations and 'не подтвержд' in row.applicability for row in r.rows)
    assert all('не подтверждено' in row.outcome for row in r.rows)
    assert 'не процент соответствия' in r.render()


def test_unknown_document_kind_and_form_never_select_tu_by_guess(tmp_path: Path) -> None:
    r=build_report(synthetic_doc(),'unconfirmed',tmp_path/'absent')
    assert r.tu_review is None
    with pytest.raises(ValueError):build_report(synthetic_doc(),'unconfirmed',tmp_path/'absent',document_form='print_framed')
    with pytest.raises(ValueError):build_report(synthetic_doc(),'technical_specifications',tmp_path/'absent',document_form='guessed')


def test_review_json_and_readable_checklist_include_every_id_without_private_content(tmp_path: Path) -> None:
    raw=synthetic_doc();r=build_report(raw,'technical_specifications',tmp_path/'absent',document_form='print_framed')
    exported=json.loads(json.dumps(asdict(r),default=_json_default))
    assert exported['tu_review']['candidate_sha256']==hashlib.sha256(raw).hexdigest()
    assert exported['document_form']=='print_framed'
    assert len(exported['tu_review']['rows'])==148
    assert not exported['full_conformance_checked'] and not exported['semantic_catalog_complete']
    text=render_catalog(load_catalog())
    assert text==Path('docs/gost-2-114-checklist.md').read_text()
    assert all(row.rule.id in text for row in r.tu_review.rows)
    assert 'TEST.123456.001' not in text


def test_gui_passes_selected_form_and_rejects_stale_attachment_dialog() -> None:
    from prilozhenie import AviationRAGApp
    app=AviationRAGApp.__new__(AviationRAGApp)
    app.is_processing=False;app.chat_manager=SimpleNamespace(current_chat_id='a')
    app._pending_attachments=[{'path':'/input/test.docx','name':'test.docx'}]
    app.page=MagicMock();app._handle_send=MagicMock();app._show_toast=MagicMock()
    app._handle_gost_click(None);dialog=app.page.open.call_args.args[0]
    assert dialog.content.controls[1].disabled
    dialog.content.controls[0].value='technical_specifications'
    dialog.content.controls[0].on_change(None)
    assert not dialog.content.controls[1].disabled
    dialog.content.controls[1].value='print_framed'
    dialog.actions[1].on_click(None)
    app._handle_send.assert_called_once_with(None,document_name='test.docx',document_kind='technical_specifications',document_form='print_framed')
    app._handle_send.reset_mock();app._handle_gost_click(None);dialog=app.page.open.call_args.args[0]
    app._pending_attachments=[]
    dialog.actions[1].on_click(None)
    app._handle_send.assert_not_called()


def test_invalid_context_is_rejected_before_any_converter(tmp_path: Path,monkeypatch: pytest.MonkeyPatch) -> None:
    import document_jobs
    converter=MagicMock();monkeypatch.setattr(document_jobs,'prepare_document',converter)
    with pytest.raises(ValueError):document_jobs.create_document('test',{},lambda _:True,document_form='electronic')
    converter.assert_not_called()


@pytest.mark.skipif(os.environ.get('BUTUZ_STANDARDS_LIVE')!='1',reason='Requires exact supplied local PDF archive')
def test_real_source_full_inventory_and_request_owned_form(tmp_path: Path) -> None:
    corpus=load(select('gost-2-114-2016'));c=load_catalog();verify_inventory(c,corpus)
    raw=synthetic_doc()
    r=build_report(raw,'technical_specifications',document_form='print_framed')
    assert r.tu_review is not None and r.tu_review.inventory_verified
    assert len(r.tu_review.rows)==148
    rows={row.rule.id:row for row in r.tu_review.rows}
    assert rows['4.8/a4'].observations
    assert 'Другая ветвь' in rows['4.9/electronic'].applicability
    assert not rows['4.9/electronic'].observations
    assert 'Другая ветвь' in rows['4.8/frameless'].applicability
    assert 'Условие требует подтверждения' in rows['5.3.2.4/service-life'].applicability
    assert 'Условие требует подтверждения' in rows['5.1.2/defense'].applicability
    assert all('не подтверждено' in x.outcome for x in rows.values())
    # A second request has its own form and byte binding; no shared callback/state.
    other=build_report(raw+b'not the same bytes','technical_specifications',document_form='electronic')
    assert other.candidate_sha256!=r.candidate_sha256
    assert other.tu_review is not None
    electronic={row.rule.id:row for row in other.tu_review.rows}
    assert 'Другая ветвь' in electronic['4.8/a4'].applicability
    assert 'Другая ветвь' not in electronic['4.9/electronic'].applicability
    assert not electronic['4.8/a4'].observations
    # Even a single changed source character invalidates span/content binding.
    altered=corpus.model_copy(update={'pages':tuple(p.model_copy(update={'text':p.text+' altered'}) if p.number==8 else p for p in corpus.pages)})
    with pytest.raises(ValueError):verify_inventory(c,altered)
    omitted=c.model_copy(update={'clauses':tuple(p for p in c.clauses if p.clause!='5.7.10'),
                                  'requirements':tuple(r for r in c.requirements if r.clause!='5.7.10')})
    with pytest.raises(ValueError):verify_inventory(omitted,corpus)


def test_approval_receives_request_form_and_exact_bytes_without_publication(tmp_path: Path,monkeypatch: pytest.MonkeyPatch) -> None:
    import document_jobs,file_tools
    from test_gost_documents import candidate
    raw=synthetic_doc();original=tmp_path/'source.docx';original.write_bytes(raw)
    monkeypatch.setattr(file_tools,'WORKSPACE',tmp_path/'chats')
    monkeypatch.setattr(document_jobs,'prepare_document',lambda *args:candidate(raw))
    monkeypatch.setattr(document_jobs,'build_report',lambda data,kind,**kw:build_report(data,kind,tmp_path/'no-library',**kw))
    seen=[]
    for form in ('print_framed','electronic'):
        def reject(proposal: document_jobs.DocumentProposal) -> bool:
            assert proposal.coverage is not None and proposal.coverage.tu_review is not None
            assert proposal.coverage.document_form==form
            assert proposal.coverage.candidate_sha256==hashlib.sha256(proposal.candidate.docx).hexdigest()
            assert proposal.coverage.tu_review.document_form==form
            assert '148' in proposal.coverage.render() and '5.7.10/equivalent' in proposal.coverage.render()
            seen.append(proposal)
            return False
        outcome=document_jobs.create_document(form,{'path':str(original)},reject,document_kind='technical_specifications',document_form=form)
        assert outcome.receipt is None and not file_tools.output_files(form)
    assert seen[0].coverage.document_form=='print_framed'
    assert original.read_bytes()==raw
