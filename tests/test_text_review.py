from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.oxml import OxmlElement
from lxml import etree as E

from text_review import review_text
from document_elements import NS,W,_numeric_columns
from text_structures import normalize_structures,expected_texts
from standard_profiles import load_profile
from gost_formatter import _texts


def test_local_reference_observations_exclude_hidden_text_and_toc(tmp_path: Path) -> None:
    doc=Document();doc.add_heading('Requirements',1)
    doc.add_paragraph('Сведения в таблице 1. См. таблицу 99 ОТУ.')
    hidden=doc.add_paragraph('См. таблицу 88.').runs[0];hidden.font.hidden=True
    doc.add_paragraph('Таблица 1');doc.add_table(rows=2,cols=2)
    out=BytesIO();doc.save(out);raw=out.getvalue()
    checks=review_text(raw);check=next(c for c in checks if c.check_id=='text-references-таблица')
    assert "цели ['1']" in check.evidence
    assert "без локальной цели ['99']" in check.evidence and '88' not in check.evidence
    assert 'ссылок 2' in check.evidence
    assert raw==out.getvalue()
    assert all(c.status!='выполнено' for c in checks)


def test_empty_native_equations_do_not_prove_absence_of_image_formulas() -> None:
    doc=Document();doc.add_heading('Requirements',1);out=BytesIO();doc.save(out)
    check=next(c for c in review_text(out.getvalue()) if c.check_id=='text-formulas-footnotes')
    assert 'Нативных формул 0' in check.evidence and 'не доказывает' in check.evidence


def test_table_label_split_only_for_adjacent_actual_caption() -> None:
    root=E.fromstring(f'<w:document xmlns:w="{W[1:-1]}"><w:body><w:p><w:pPr><w:pStyle w:val="H1"/></w:pPr><w:r><w:t>Requirements</w:t></w:r></w:p><w:p><w:r><w:t>Таблица 1</w:t></w:r></w:p><w:tbl/><w:p><w:r><w:t>Таблица 2 упомянута в тексте.</w:t></w:r></w:p></w:body></w:document>')
    before=_texts(root);report=normalize_structures(root,None,None,{'H1':'heading1'},load_profile())
    assert report.table_labels==1 and _texts(root)==expected_texts(before,report.splits)
    texts=root.xpath('//w:p[2]/w:r/w:t/text()',namespaces=NS)
    assert texts==['Таблица',' 1']


def test_numeric_alignment_does_not_rewrite_or_center_mixed_prose_columns() -> None:
    doc=Document();table=doc.add_table(rows=4,cols=3)
    for row,values in zip(table.rows,[['Name','Value','Mixed'],['A','1.2','1'],['B','2.3','text'],['C','—','3']]):
        for cell,text in zip(row.cells,values):cell.text=text
    root=E.fromstring(E.tostring(table._tbl));rows=root.findall(W+'tr')
    before=E.tostring(table._tbl)
    assert _numeric_columns(rows,1)=={1}
    assert E.tostring(table._tbl)==before
    prop=OxmlElement('w:trPr');skip=OxmlElement('w:gridBefore');skip.set(W+'val','1');prop.append(skip);rows[2].insert(0,prop)
    assert _numeric_columns(rows,1)==set()
