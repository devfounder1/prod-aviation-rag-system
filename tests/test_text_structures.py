from __future__ import annotations

import copy
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from docx import Document
from docx.oxml import OxmlElement
from lxml import etree as ET
import pytest

from document_elements import NS,W
from gost_formatter import format_docx,_texts
from standard_profiles import load_profile
from text_structures import normalize_structures,expected_texts,TextSplit


def tree(content: str) -> Any:
    return ET.fromstring(f'<w:document xmlns:w="{W[1:-1]}"><w:body>{content}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:left="1440" w:right="1440"/></w:sectPr></w:body></w:document>')


def p(text: str,style: str = '') -> str:
    pr=f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ''
    return f'<w:p>{pr}<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def main(content: str) -> Any:
    return tree(p('Requirements','H1')+content)


def normalize(root: Any) -> Any:
    return normalize_structures(root,None,None,{'H1':'heading1'},load_profile())


def test_note_label_split_is_exact_and_retains_run_properties_and_technical_values() -> None:
    root=main(p('Примечание — оставить 27 В и формулу x = 2.'))
    run=root.findall('w:body/w:p',NS)[1].find(W+'r')
    prop=ET.Element(W+'rPr');ET.SubElement(prop,W+'b').set(W+'val','1');run.insert(0,prop)
    before=_texts(root);report=normalize(root)
    assert report.notes==1 and len(report.splits)==1
    assert _texts(root)==expected_texts(before,report.splits)
    note=root.findall('w:body/w:p',NS)[1];runs=note.findall(W+'r')
    assert [r.find(W+'t').text for r in runs]==['Примечание',' — оставить 27 В и формулу x = 2.']
    assert all(r.find('w:rPr/w:b',NS).get(W+'val')=='1' for r in runs)
    assert all(r.find('w:rPr/w:sz',NS).get(W+'val')=='24' for r in runs)
    assert runs[0].find('w:rPr/w:spacing',NS).get(W+'val')=='20'
    assert runs[1].find('w:rPr/w:spacing',NS) is None
    assert runs[1].find(W+'t').get('{http://www.w3.org/XML/1998/namespace}space')=='preserve'
    assert note.find('w:pPr/w:spacing',NS).get(W+'line')=='360'


@pytest.mark.parametrize('split',[
    TextSplit(0,'abc','a','changed'),TextSplit(8,'abc','a','bc'),TextSplit(0,'wrong','a','bc'),TextSplit(0,'abc','','abc')])
def test_text_ledger_cannot_authorize_other_text_changes(split: TextSplit) -> None:
    with pytest.raises(ValueError):expected_texts([(W+'t','abc')],(split,))


@pytest.mark.parametrize('text',['Примечания должны быть понятными.','Пример использования программы.','Примечание описано в другом разделе.'])
def test_mentions_are_not_reinterpreted_as_notes(text: str) -> None:
    root=main(p(text));before=ET.tostring(root)
    report=normalize(root)
    assert report.notes==report.examples==0 and ET.tostring(root)==before


def test_title_fields_and_drawings_stay_protected() -> None:
    root=tree(p('Примечание — title')+p('Requirements','H1')+'<w:p><w:r><w:fldChar w:fldCharType="begin"/><w:t>Примечание — field</w:t></w:r></w:p>')
    original=[ET.tostring(q) for q in root.findall('w:body/w:p',NS)]
    assert normalize(root).notes==0
    assert [ET.tostring(q) for q in root.findall('w:body/w:p',NS)]==original


def toc_root(anchor: str='target',role: str='toc1',entry: str='1') -> Any:
    return tree(p('Содержание')+f'''<w:sdt><w:sdtPr><w:docPartObj><w:docPartGallery w:val="Table of Contents"/></w:docPartObj></w:sdtPr><w:sdtContent><w:p><w:pPr><w:pStyle w:val="toc"/></w:pPr><w:hyperlink w:anchor="{anchor}"><w:r><w:t>{entry}</w:t><w:tab/><w:t>Long heading for wrapping</w:t><w:tab/><w:t>2</w:t></w:r></w:hyperlink></w:p></w:sdtContent></w:sdt>'''+p('Requirements','H1').replace('<w:r>','<w:bookmarkStart w:id="1" w:name="target"/><w:r>',1))


def test_existing_toc_uses_dot_leader_and_hanging_wrap_without_changing_fields() -> None:
    root=toc_root();before=_texts(root)
    report=normalize_structures(root,None,None,{'H1':'heading1','toc':'toc2'},load_profile())
    assert report.toc_entries==1 and _texts(root)==before
    entry=root.find('.//w:sdtContent/w:p',NS)
    assert entry.find('w:pPr/w:ind',NS).get(W+'hanging')=='709'
    assert entry.find('w:pPr/w:tabs/w:tab[@w:val="right"]',NS).get(W+'leader')=='dot'
    assert entry.find('w:pPr/w:ind',NS).get(W+'right')=='567'
    assert root.find('w:body/w:p/w:pPr/w:jc',NS).get(W+'val')=='center'


@pytest.mark.parametrize('anchor,entry',[('missing','1'),('target','not-a-number')])
def test_ambiguous_toc_preserved(anchor: str,entry: str) -> None:
    root=toc_root(anchor,entry=entry);before=ET.tostring(root.find('.//w:sdtContent/w:p',NS))
    report=normalize_structures(root,None,None,{'H1':'heading1','toc':'toc1'},load_profile())
    assert report.toc_entries==0 and report.warnings
    assert ET.tostring(root.find('.//w:sdtContent/w:p',NS))==before


def test_appendix_heading_existing_three_lines_is_centered_not_renumbered() -> None:
    root=main(p('Приложение А').replace('</w:t>','</w:t><w:br/><w:t>(обязательное)</w:t><w:br/><w:t>Existing appendix title</w:t>',1))
    before=_texts(root);report=normalize(root)
    assert report.appendix_headings==1 and _texts(root)==before
    header=root.findall('w:body/w:p',NS)[1]
    assert header.find('w:pPr/w:jc',NS).get(W+'val')=='center'
    assert header.find('w:pPr/w:pageBreakBefore',NS).get(W+'val')=='1'


def test_example_uses_smaller_bold_italic_without_rewriting_code() -> None:
    root=main(p('Пример — print("hello")'));before=_texts(root)
    report=normalize(root)
    assert report.examples==1 and _texts(root)==before
    run=root.findall('w:body/w:p',NS)[1].find(W+'r')
    assert run.find('w:rPr/w:b',NS).get(W+'val')=='1'
    assert run.find('w:rPr/w:i',NS).get(W+'val')=='1'
    assert run.find('w:rPr/w:sz',NS).get(W+'val')=='24'


def test_formatter_verifies_label_partitions_and_preserves_other_zip_parts(tmp_path: Path) -> None:
    doc=Document();doc.add_heading('Requirements',1);doc.add_paragraph('Примечание — source literal 27 В.')
    source,target=tmp_path/'source.docx',tmp_path/'result.docx';doc.save(source)
    original=source.read_bytes();report=format_docx(source,target)
    assert source.read_bytes()==original and report.body_text_preserved
    assert Document(target).paragraphs[1].text=='Примечание — source literal 27\xa0В.'
    with ZipFile(source) as a,ZipFile(target) as b:
        assert all(a.read(n)==b.read(n) for n in a.namelist() if n not in {'word/document.xml','word/settings.xml'})


def test_body_and_note_sizes_preserve_cover_emphasis_and_superscripts(tmp_path: Path) -> None:
    from docx.shared import Pt
    doc=Document();doc.styles['Normal'].font.size=Pt(11)
    cover=doc.add_paragraph('Unchanged cover').runs[0];cover.font.size=Pt(9)
    doc.add_paragraph('Настоящие технические условия относятся к изделию.')
    doc.add_heading('Requirements',1)
    body=doc.add_paragraph();body.add_run('Current body ').bold=True
    script=body.add_run('2');script.font.superscript=True;script.font.size=Pt(8)
    doc.add_paragraph('Примечание — literal note.')
    source,target=tmp_path/'source.docx',tmp_path/'result.docx';doc.save(source)
    format_docx(source,target);result=Document(target)
    assert result.paragraphs[0].runs[0].font.size.pt==9
    assert result.paragraphs[1].runs[0].font.size.pt==14
    assert result.paragraphs[3].runs[0].font.size.pt==14
    assert result.paragraphs[3].runs[0].bold
    assert result.paragraphs[3].runs[1].font.size.pt==8
    assert result.paragraphs[3].runs[1].font.superscript
    assert all(r.font.size.pt==12 for r in result.paragraphs[4].runs)


def test_toc_title_is_styled_even_with_separate_page_column_label() -> None:
    root=toc_root();body=root.find(W+'body');body.insert(1,tree(p('Лист')).find('w:body/w:p',NS))
    report=normalize_structures(root,None,None,{'H1':'heading1','toc':'toc1'},load_profile())
    assert report.toc_entries==1
    heading=body.find(W+'p')
    assert heading.find('w:r/w:rPr/w:b',NS).get(W+'val')=='1'
    assert body.findall(W+'p')[1].find('w:r/w:rPr',NS) is None


@pytest.mark.skipif(__import__('os').environ.get('BUTUZ_DOCUMENTS_LIVE')!='1',reason='Requires prepared local document image')
def test_rendered_note_font_tracking_and_toc_wrap(tmp_path: Path) -> None:
    from io import BytesIO
    from docx.shared import Mm,Pt
    from docx.enum.style import WD_STYLE_TYPE
    import pdfplumber
    from document_runner import prepare_document
    doc=Document();doc.styles['Normal'].font.name='Liberation Serif';doc.styles['Normal'].font.size=Pt(14)
    sec=doc.sections[0];sec.page_width=Mm(210);sec.page_height=Mm(297);sec.left_margin=Mm(30);sec.right_margin=Mm(10)
    doc.add_paragraph('Содержание');doc.styles.add_style('TOC 1',WD_STYLE_TYPE.PARAGRAPH)
    toc=ET.fromstring(f'''<w:sdt xmlns:w="{W[1:-1]}"><w:sdtPr><w:docPartObj><w:docPartGallery w:val="Table of Contents"/></w:docPartObj></w:sdtPr><w:sdtContent><w:p><w:pPr><w:pStyle w:val="TOC1"/></w:pPr><w:hyperlink w:anchor="target"><w:r><w:t>1</w:t><w:tab/><w:t>Alpha existing title repeated for proving continuation alignment of the long heading in an editable table of contents</w:t><w:tab/><w:t>2</w:t></w:r></w:hyperlink></w:p></w:sdtContent></w:sdt>''')
    doc._element.body.insert(1,toc)
    heading=doc.add_heading('Alpha existing title repeated for proving continuation alignment of the long heading in an editable table of contents',1)
    bookmark=OxmlElement('w:bookmarkStart');bookmark.set(W+'name','target');bookmark.set(W+'id','1');heading._p.insert(0,bookmark)
    end=OxmlElement('w:bookmarkEnd');end.set(W+'id','1');heading._p.append(end)
    doc.add_paragraph('Body text remains at fourteen points.')
    doc.add_paragraph('Примечание — Existing source note with 27 В. A second sentence remains intact.')
    source=tmp_path/'source.docx';doc.save(source);raw=source.read_bytes()
    result=prepare_document(source);assert source.read_bytes()==raw
    with pdfplumber.open(BytesIO(result.preview_pdf)) as pdf:
        first=pdf.pages[0];words=first.extract_words()
        start=next(w for w in words if w['text']=='Alpha')
        continuation=min((w for w in words if w['top']>start['top']+8 and not w['text'].isdigit()),key=lambda w:w['top'])
        # A wrapped TOC title starts under its title, not under the section number.
        assert continuation['x0']==pytest.approx(start['x0'],abs=1)
        assert any(c['text']=='.' for c in first.chars)
        note_page=next(p for p in pdf.pages if 'Existing source note' in (p.extract_text() or ''))
        for word in ('Existing','source','note'):
            found=next(w for w in note_page.extract_words(extra_attrs=['size']) if w['text']==word)
            assert found['size']==pytest.approx(12,abs=.2)
    assert 'Примечание — Existing source note' in Document(BytesIO(result.docx)).paragraphs[-1].text
