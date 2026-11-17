from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from docx import Document
from docx.shared import Mm
import pytest

from tu_validation import validate_tu, verify_preview


def make_doc(tmp_path: Path, bad_spacing: bool = False) -> bytes:
    doc=Document();doc.sections[0].page_width=Mm(210);doc.sections[0].page_height=Mm(297)
    doc.add_paragraph('Настоящие технические условия распространяются на тестовое изделие.')
    # A TOC-looking entry must not become a real section.
    doc.add_paragraph('Гарантии изготовителя',style='TOC Heading')
    doc.add_heading('Технические требования',1)
    p=doc.add_paragraph('Технические данные и ссылка TEST.123456.001 ТУ.')
    p.paragraph_format.line_spacing=1.0 if bad_spacing else 1.5
    p.paragraph_format.space_before=Mm(0);p.paragraph_format.space_after=Mm(0)
    caption=doc.add_paragraph('Таблица 1');caption.paragraph_format.line_spacing=1.0
    doc.add_table(rows=2,cols=2)
    # Numbered requirements are body content, not section headings.
    p=doc.add_heading('Требования безопасности',3)
    p.paragraph_format.line_spacing=1.5;p.paragraph_format.space_before=Mm(0);p.paragraph_format.space_after=Mm(0)
    doc.add_heading('Правила приёмки',1)
    doc.add_heading('Методы испытаний',1)
    path=tmp_path/'fixture.docx';doc.save(path)
    return path.read_bytes()


def test_measurements_do_not_certify_section_composition(tmp_path: Path) -> None:
    checks=validate_tu(make_doc(tmp_path))
    assert next(c for c in checks if c.check_id=='page-size').status=='измерено'
    spacing=next(c for c in checks if c.check_id=='body-spacing')
    assert spacing.status=='измерено' and 'Абзацев: 2;' in spacing.evidence
    safety=next(c for c in checks if c.scope.startswith('Требования безопасности —'))
    warranty=next(c for c in checks if c.scope.startswith('Гарантии изготовителя —'))
    assert safety.status==warranty.status=='требует подтверждения'
    assert 'Отсутствие заголовка не признано нарушением' in safety.evidence
    assert 'TEST.123456.001 ТУ' in checks[-1].evidence


def test_bad_spacing_and_invalid_package_cannot_pass(tmp_path: Path) -> None:
    checks=validate_tu(make_doc(tmp_path,True))
    assert next(c for c in checks if c.check_id=='body-spacing').status=='требует проверки'
    invalid=validate_tu(b'not a document')
    assert len(invalid)==1 and invalid[0].status=='не поддерживается'


def test_unknown_section_size_is_not_inferred_as_a4(tmp_path: Path) -> None:
    from docx.oxml.ns import qn
    doc=Document(BytesIO(make_doc(tmp_path)))
    section=doc.add_section()
    section._sectPr.remove(section._sectPr.find(qn('w:pgSz')))
    path=tmp_path/'unknown-size.docx';doc.save(path)
    checks=validate_tu(path.read_bytes())
    assert next(c for c in checks if c.check_id=='page-size').status=='требует проверки'


@pytest.mark.parametrize('pages,valid',[([1,2],True),([1,1],False),([2,2],False),([1],False),([],False)])
def test_final_pdf_requires_captions_on_distinct_pages(
    tmp_path: Path,monkeypatch: pytest.MonkeyPatch,pages: list[int],valid: bool,
) -> None:
    import pdfplumber
    doc=Document()
    for _ in range(2):
        doc.add_paragraph('Продолжение таблицы 3');doc.add_table(rows=2,cols=2)
    path=tmp_path/'captioned.docx';doc.save(path)
    rendered=MagicMock()
    rendered.__enter__.return_value.pages=[SimpleNamespace(height=800,width=600,search=lambda _,idx=i: [
        {'top':40,'bottom':52,'x0':40,'x1':240} for p in pages if p==idx]) for i in range(3)]
    monkeypatch.setattr(pdfplumber,'open',lambda _:rendered)
    if valid:
        assert verify_preview(path.read_bytes(),b'provided by test renderer')==2
    else:
        with pytest.raises(ValueError,match='отсутствует'): verify_preview(path.read_bytes(),b'fixture')


def test_invalid_pdf_caption_geometry_is_not_approved(tmp_path: Path,monkeypatch: pytest.MonkeyPatch) -> None:
    import pdfplumber
    doc=Document();doc.add_paragraph('Продолжение таблицы 3');doc.add_table(rows=2,cols=2)
    path=tmp_path/'c.docx';doc.save(path)
    rendered=MagicMock();rendered.__enter__.return_value.pages=[SimpleNamespace(height=800,width=600,
        search=lambda _: [{'top':-3,'bottom':8,'x0':40,'x1':240}])]
    monkeypatch.setattr(pdfplumber,'open',lambda _:rendered)
    with pytest.raises(ValueError,match='выходит'): verify_preview(path.read_bytes(),b'fixture')


def test_plain_mention_without_table_is_not_a_caption(tmp_path: Path) -> None:
    doc=Document();doc.add_paragraph('Продолжение таблицы 3');doc.add_paragraph('Example text only')
    path=tmp_path/'example.docx';doc.save(path)
    assert verify_preview(path.read_bytes(),b'No preview needed for a non-caption')==0
