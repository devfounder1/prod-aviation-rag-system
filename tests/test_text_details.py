from io import BytesIO
from docx import Document
from docx.oxml import OxmlElement

from text_details import review_details,locations


def sample() -> bytes:
    doc=Document();doc.add_paragraph('Примечание: Напряжение сохраняется.')
    doc.add_paragraph('По п. 3.5.1. настоящих 1 ТУ.')
    doc.add_paragraph('Ряд: 0 мА, 1 мА, 2 мА.')
    doc.add_table(rows=1,cols=1).cell(0,0).text='± (0,002 Uуст + 0,1) В'
    doc.add_paragraph('Температура от плюс 5 °C до плюс 55 °C.')
    out=BytesIO();doc.save(out);return out.getvalue()


def test_real_candidates_include_cell_addresses_without_mutating_bytes() -> None:
    import hashlib
    raw=sample();digest=hashlib.sha256(raw).hexdigest();checks={c.check_id:c for c in review_details(raw)}
    assert 'b1:' in checks['text-detail-note-label'].evidence
    assert 'b2:' in checks['text-detail-reference-format'].evidence
    assert 'Найдено 1.' in checks['text-detail-unit-series'].evidence
    assert 'b4/r1/c1/p1:' in checks['text-detail-formula-text'].evidence
    assert hashlib.sha256(raw).hexdigest()==digest
    assert all(c.status!='выполнено' for c in checks.values())


def test_hidden_styled_field_and_hyperlink_text_is_not_used_as_a_finding() -> None:
    from docx.enum.style import WD_STYLE_TYPE
    doc=Document();s=doc.styles.add_style('HiddenCustom',WD_STYLE_TYPE.PARAGRAPH);s.font.hidden=True
    doc.add_paragraph('Примечание: hidden',style=s)
    doc.add_paragraph('Примечание: hidden').runs[0].font.hidden=True
    p=doc.add_paragraph();link=OxmlElement('w:hyperlink');run=OxmlElement('w:r');t=OxmlElement('w:t');t.text='Примечание: linked';run.append(t);link.append(run);p._p.append(link)
    p=doc.add_paragraph();field=OxmlElement('w:fldSimple');p._p.append(field)
    out=BytesIO();doc.save(out)
    assert locations(out.getvalue())==()


def test_bounded_evidence_discloses_truncation() -> None:
    doc=Document()
    for i in range(20):doc.add_paragraph(f'Примечание: item {i}')
    out=BytesIO();doc.save(out)
    check=next(c for c in review_details(out.getvalue()) if c.check_id=='text-detail-note-label')
    assert 'Найдено 20.' in check.evidence and 'показаны 12 из 20' in check.evidence


def test_formula_visible_prefix_is_retained_and_cyrillic_prose_is_not_math() -> None:
    doc=Document();p=doc.add_paragraph('± (0,002 Uуст + 0,1) В')
    p.add_run(' SECRET = 5').font.hidden=True
    doc.add_paragraph('Напряжение (27 ± 2) В и изменение питания в диапазоне.')
    out=BytesIO();doc.save(out)
    check=next(c for c in review_details(out.getvalue()) if c.check_id=='text-detail-formula-text')
    assert 'Найдено 1.' in check.evidence and 'Uуст' in check.evidence
    assert 'SECRET' not in check.evidence
