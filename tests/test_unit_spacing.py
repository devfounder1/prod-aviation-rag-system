from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from docx import Document
from lxml import etree as ET
import pytest

from document_elements import NS,W
from gost_formatter import format_docx
from unit_spacing import bind_units


def root(content: str) -> Any:
    return ET.fromstring(f'<w:document xmlns:w="{W[1:-1]}"><w:body>{content}</w:body></w:document>'.encode())


def paragraph(text: str) -> str:
    return f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


@pytest.mark.parametrize('source,expected',[
    ('плюс 55 °С;', 'плюс 55\xa0°С;'),
    ('минус 50 °C;', 'минус 50\xa0°C;'),
    ('5 ° C;', '5\xa0°\xa0C;'),
    ('27,0 В; 0,5 мА; 10 мкс; 80 %;', '27,0\xa0В; 0,5\xa0мА; 10\xa0мкс; 80\xa0%;'),
    ('(5 ± 0,5) В', '(5\xa0±\xa00,5)\xa0В'),
    ('1 000 кг; 1,5e-3 м', '1\xa0000\xa0кг; 1,5e-3\xa0м'),
    ('525 мм рт. ст.', '525\xa0мм\xa0рт.\xa0ст.'),
    ('9,8 м/с²', '9,8\xa0м/с²'),
    ('50 с.', '50\xa0с.'),
    ('55\xa0°С; 5\u202fВ', '55\xa0°С; 5\u202fВ'),
])
def test_exact_known_quantity_whitespace_only(source: str,expected: str) -> None:
    r = root(paragraph(source));before = [ET.tostring(p) for p in r.findall('.//w:rPr',NS)]
    bind_units(r)
    assert ''.join(r.xpath('//w:t/text()',namespaces=NS))==expected
    assert [ET.tostring(p) for p in r.findall('.//w:rPr',NS)]==before
    assert bind_units(r).spaces==0  # idempotent


def test_runs_and_styles_are_retained_across_value_unit_boundary() -> None:
    r = root('<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>55</w:t></w:r><w:r><w:rPr><w:i/></w:rPr><w:t xml:space="preserve"> </w:t></w:r><w:r><w:t>°</w:t></w:r><w:r><w:t>С;</w:t></w:r></w:p>')
    runs = r.findall('.//w:r',NS); props = [ET.tostring(n) for n in r.findall('.//w:rPr',NS)]
    result = bind_units(r)
    assert result.quantities==1 and result.spaces==1
    assert r.findall('.//w:r',NS)==runs
    assert [ET.tostring(n) for n in r.findall('.//w:rPr',NS)]==props
    assert r.xpath('//w:t/text()',namespaces=NS)==['55','\xa0','°','С;']


@pytest.mark.parametrize('value',[
    '2026 г.', 'пункт 3 с указанием значения', '1.2.3 В документе',
    'модуль A55 В', '55 °Сигнал', 'Файл 3.14.py', '5 неизвестных',
])
def test_years_prepositions_identifiers_and_unknown_units_are_not_rewritten(value: str) -> None:
    r = root(paragraph(value));before = ET.tostring(r)
    assert bind_units(r).spaces==0 and ET.tostring(r)==before


@pytest.mark.parametrize('construct',[
    '<w:p><w:r><w:fldChar w:fldCharType="begin"/><w:t>55 °С</w:t></w:r></w:p>',
    '<w:p><w:fldSimple w:instr="REF other"><w:r><w:t>55 °С</w:t></w:r></w:fldSimple></w:p>',
    '<w:p><w:hyperlink><w:r><w:t>55 °С</w:t></w:r></w:hyperlink></w:p>',
    '<w:p><w:del><w:r><w:delText>55 °С</w:delText></w:r></w:del></w:p>',
    '<w:p><w:r><w:pict><w:txbxContent>'+paragraph('55 °С')+'</w:txbxContent></w:pict></w:r></w:p>',
])
def test_fields_revisions_and_drawing_text_stay_opaque(construct: str) -> None:
    r=root(construct);before=ET.tostring(r)
    assert bind_units(r).spaces==0 and ET.tostring(r)==before


def test_table_cells_supported_but_breaks_tabs_and_paragraph_boundaries_are_not_joined() -> None:
    r=root('<w:tbl><w:tr><w:tc>'+paragraph('55 °С')+'</w:tc></w:tr></w:tbl>')
    assert bind_units(r).spaces==1
    for boundary in ('<w:br/>','<w:br w:type="page"/>','<w:tab/>'):
        r=root('<w:p><w:r><w:t>55</w:t>'+boundary+'<w:t>°С</w:t></w:r></w:p>');before=ET.tostring(r)
        result=bind_units(r)
        assert result.spaces==0 and result.warnings and ET.tostring(r)==before
    r=root(paragraph('55')+paragraph('°С'));before=ET.tostring(r)
    assert bind_units(r).spaces==0 and ET.tostring(r)==before


def test_formatter_changes_only_authorized_spaces_and_retains_all_other_parts(tmp_path: Path) -> None:
    doc=Document();doc.add_heading('Requirements',1)
    p=doc.add_paragraph();p.add_run('55').bold=True;p.add_run(' ');p.add_run('°С;').italic=True
    source,target=tmp_path/'source.docx',tmp_path/'result.docx';doc.save(source)
    original=source.read_bytes();report=format_docx(source,target)
    assert source.read_bytes()==original and report.body_text_preserved
    assert Document(target).paragraphs[1].text=='55\xa0°С;'
    assert any('единицами: 1' in x for x in report.changes)
    with ZipFile(source) as a,ZipFile(target) as b:
        assert all(a.read(n)==b.read(n) for n in a.namelist() if n not in {'word/document.xml','word/settings.xml'})


@pytest.mark.skipif(os.environ.get('BUTUZ_DOCUMENTS_LIVE')!='1',reason='Requires prepared local document image')
def test_actual_pdf_keeps_value_and_unit_together_at_line_end(tmp_path: Path) -> None:
    from docx.shared import Mm,Pt
    import pdfplumber
    from document_runner import prepare_document
    doc=Document();doc.styles['Normal'].font.size=Pt(14)
    # Deliberately narrow area forces the reported end-of-line case.
    doc.sections[0].left_margin=Mm(25);doc.sections[0].right_margin=Mm(120)
    doc.add_heading('Requirements',1)
    for _ in range(4):
        p=doc.add_paragraph('После воздействия температуры плюс ')
        p.add_run('55').bold=True;p.add_run(' ');p.add_run('°С;')
    source=tmp_path/'source.docx';doc.save(source)
    candidate=prepare_document(source)
    hits=0
    with pdfplumber.open(io.BytesIO(candidate.preview_pdf)) as pdf:
        for page in pdf.pages:
            words=page.extract_words(x_tolerance=1,y_tolerance=2)
            for i,word in enumerate(words):
                if word['text']=='55':
                    unit=words[i+1]
                    assert unit['text']=='°С;'
                    assert abs(word['top']-unit['top'])<2
                    hits+=1
    assert hits==4
