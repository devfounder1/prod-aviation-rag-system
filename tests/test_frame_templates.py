from dataclasses import replace
import hashlib
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as E

from docx import Document
import pytest

from frame_templates import make_header, StampValues, ApprovalRow, HeaderReplacement, replace_furniture, NS
from stamp_review import measure_header


def test_forms_have_page_coordinates_new_version_fields_and_185mm_geometry() -> None:
    values=StampValues(designation='SYNTHETIC ТУ',approvals=(ApprovalRow('Разраб.'),))
    for form,height in (('2',40),('2a',15)):
        raw=make_header(form,values);root=E.fromstring(raw)
        frame=measure_header(root)[0]
        assert frame.width_mm==185 and frame.height_mm==287
        assert frame.stamp_height_mm==height
        assert root.find('.//wp:positionH/wp:posOffset',NS).text=='0'
        assert root.find('.//wp:positionV/wp:posOffset',NS).text=='0'
        text=[n.text for n in root.iter('{'+NS['w']+'}t')]
        assert 'Вер.' in text and 'Лист' in text
        assert 'SYNTHETIC ТУ' in text and 'Н. контр.' not in text
        assert not list(root.iter('{'+NS['w']+'}object'))


def source_bytes() -> bytes:
    d=Document();d.add_paragraph('Technical body must remain EXACTLY unchanged. 55 °C')
    from docx.shared import Mm
    d.sections[0].page_width=Mm(210);d.sections[0].page_height=Mm(297)
    d.sections[0].header.paragraphs[0].text='Existing frame and signature'
    b=BytesIO();d.save(b);return b.getvalue()


def plan(raw: bytes) -> HeaderReplacement:
    with ZipFile(BytesIO(raw)) as z:
        return HeaderReplacement('word/header1.xml',hashlib.sha256(z.read('word/header1.xml')).hexdigest(),make_header('2a'))


def test_rebinding_retains_all_original_parts_body_and_media_byte_for_byte() -> None:
    raw=source_bytes();p=plan(raw);result=replace_furniture(raw,hashlib.sha256(raw).hexdigest(),(p,))
    with ZipFile(BytesIO(raw)) as a,ZipFile(BytesIO(result)) as b:
        assert set(a.namelist())<=set(b.namelist())
        assert all(a.read(n)==b.read(n) for n in a.namelist() if n not in {'[Content_Types].xml','word/_rels/document.xml.rels'})
        assert b.read('word/header9001.xml')==p.new_xml
        assert b'header9001.xml' in b.read('word/_rels/document.xml.rels')


def test_stale_plan_wrong_kind_and_duplicate_replacements_fail_closed() -> None:
    raw=source_bytes();p=plan(raw);sha=hashlib.sha256(raw).hexdigest()
    for expected,items in (('0'*64,(p,)),(sha,(replace(p,source_sha256='0'*64),)),
                           (sha,(p,p)),(sha,(replace(p,new_xml=b'<bad/>'),))):
        with pytest.raises(ValueError):replace_furniture(raw,expected,items)


def test_render_only_requires_docx_before_starting_docker(tmp_path: Path) -> None:
    from document_runner import prepare_document
    source=tmp_path/'source.doc';source.write_bytes(b'legacy')
    with pytest.raises(ValueError,match='DOCX'):prepare_document(source,render_only=True)


@pytest.mark.skipif(__import__('os').environ.get('BUTUZ_DOCUMENTS_LIVE')!='1',reason='prepared document image')
def test_render_only_returns_exact_bytes_with_new_editable_frames(tmp_path: Path) -> None:
    from document_runner import prepare_document
    raw=source_bytes();p=plan(raw)
    updated=replace_furniture(raw,hashlib.sha256(raw).hexdigest(),(p,))
    source=tmp_path/'framed.docx';source.write_bytes(updated)
    c=prepare_document(source,render_only=True)
    assert c.docx==updated and len(c.pages)==1
    from frame_preview import observe_frames
    row=observe_frames(c.preview_pdf)[0]
    assert row.left_mm==pytest.approx(20,abs=.1) and row.top_mm==pytest.approx(5,abs=.1)
    assert row.width_mm==pytest.approx(185,abs=.1)
    assert row.stamp_height_mm==pytest.approx(15,abs=.1)


@pytest.mark.skipif(__import__('os').environ.get('BUTUZ_DOCUMENTS_LIVE')!='1',reason='prepared document image')
def test_two_page_template_text_and_vertical_labels_stay_in_cells(tmp_path: Path) -> None:
    from frame_templates import blank_template
    from document_runner import prepare_document
    import pdfplumber
    raw=blank_template();source=tmp_path/'blank.docx';source.write_bytes(raw)
    c=prepare_document(source,render_only=True)
    assert c.docx==raw and len(c.pages)==2
    mm=25.4/72
    with pdfplumber.open(BytesIO(c.preview_pdf)) as pdf:
        for page in pdf.pages:
            assert page.chars
            assert all(8-.1<=ch['x0']*mm and ch['x1']*mm<=205+.1 for ch in page.chars)
            vertical=[ch for ch in page.chars if ch['x0']*mm<13]
            assert vertical and all(not ch['upright'] for ch in vertical)
            versions=[word for word in page.extract_words() if word['text']=='Вер.']
            assert len(versions)==1
            assert 277<=versions[0]['top']*mm<=282 if page.page_number==2 else 252<=versions[0]['top']*mm<=257
