from __future__ import annotations

from pathlib import Path
from typing import Any
from zipfile import ZipFile

from docx import Document
from lxml import etree as ET
import pytest
import os

from document_elements import NS, W
from gost_formatter import format_docx
from list_layout import normalize_lists


def xml(value: str) -> Any:
    return ET.fromstring(value.encode())


def numbering(marker: str = '%1)', kind: str = 'decimal') -> Any:
    return xml(f'''<w:numbering xmlns:w="{W[1:-1]}"><w:abstractNum w:abstractNumId="9">
    <w:lvl w:ilvl="0"><w:numFmt w:val="{kind}"/><w:lvlText w:val="{marker}"/>
    <w:pPr><w:tabs><w:tab w:val="num" w:pos="720"/></w:tabs><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl>
    <w:lvl w:ilvl="1"><w:numFmt w:val="lowerRoman"/><w:lvlText w:val="%2)"/></w:lvl>
    </w:abstractNum><w:num w:numId="22"><w:abstractNumId w:val="9"/></w:num></w:numbering>''')


def item(text: str, level: int = 0, extra: str = '') -> str:
    return f'''<w:p><w:pPr><w:numPr><w:ilvl w:val="{level}"/><w:numId w:val="22"/></w:numPr>
    <w:ind w:start="1000" w:hanging="400" w:firstLineChars="50"/>{extra}</w:pPr><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'''


def document(content: str) -> Any:
    return xml(f'<w:document xmlns:w="{W[1:-1]}"><w:body>{content}</w:body></w:document>')


def test_nested_lists_use_positive_first_line_not_hanging_and_keep_exact_numbers_text() -> None:
    root = document('<w:p><w:r><w:t>Intro:</w:t></w:r></w:p>'+item('parent:', 0) + item('nested;', 1) + item('last nested.', 1) + item('last parent.', 0))
    nums = numbering(); before = ET.tostring(nums)
    texts = root.xpath('.//w:t/text()', namespaces=NS)
    report = normalize_lists(root, None, nums, 12.5)
    assert report.items == 4 and not report.warnings
    assert root.xpath('.//w:t/text()', namespaces=NS) == texts
    assert ET.tostring(nums.find("w:abstractNum[@w:abstractNumId='9']",NS)) == ET.tostring(ET.fromstring(before).find(W+'abstractNum'))
    assert nums.find("w:num[@w:numId='22']",NS) is not None
    for p, left in zip(root.findall('w:body/w:p', NS)[1:], (0,709,709,0), strict=True):
        ind = p.find('w:pPr/w:ind', NS)
        assert ind.get(W+'left') == ind.get(W+'start') == str(left)
        assert ind.get(W+'firstLine') == '709'
        assert ind.get(W+'hanging') is None and ind.get(W+'firstLineChars') is None
        assert p.find('w:pPr/w:spacing', NS).get(W+'line') == '360'
        assert p.find('w:pPr/w:tabs/w:tab[@w:val="num"]', NS).get(W+'pos') == str(left+1069)


def test_soft_break_requires_whitespace_and_does_not_touch_page_column_or_text() -> None:
    p = item('before ').replace('</w:t>', '</w:t><w:br/><w:t>after</w:t>', 1)
    root = document(p + item('last.'))
    before = root.xpath('.//w:t/text()', namespaces=NS)
    assert normalize_lists(root, None, numbering(), 12.5).soft_breaks == 1
    assert root.xpath('.//w:t/text()', namespaces=NS) == before
    for mark in ('<w:br w:type="page"/>', '<w:br w:type="column"/>', '<w:br w:clear="all"/>', '<w:br/>'):
        root = document(item('before').replace('</w:t>', '</w:t>'+mark+'<w:t>after</w:t>', 1) + item('last.'))
        assert normalize_lists(root, None, numbering(), 12.5).soft_breaks == 0
        assert len(root.findall('.//w:r/w:br', NS)) == 1


def test_numbered_notes_keep_period_labels_and_sentence_punctuation() -> None:
    root = document('<w:p><w:r><w:t>Примечания:</w:t></w:r></w:p>'+item('First sentence.')+item('Second sentence.'))
    nums = numbering('%1.')
    report = normalize_lists(root, None, nums, 12.5)
    assert report.notes == 2 and report.items == 0 and not report.warnings
    assert root.findall('w:body/w:p', NS)[1].find('w:pPr/w:ind', NS).get(W+'firstLine') == '709'
    assert nums.find('.//w:lvlText', NS).get(W+'val') == '%1.'


@pytest.mark.parametrize('extra,marker', [('<w:pStyle w:val="H3"/>','%1)'), ('','%1.%2.'), ('<w:outlineLvl w:val="2"/>','%1)')])
def test_technical_requirements_and_headings_unchanged(extra: str, marker: str) -> None:
    root = document(item('technical 27.5 V',extra=extra)+item('other',extra=extra))
    styles = xml(f'<w:styles xmlns:w="{W[1:-1]}"><w:style w:styleId="H3"><w:name w:val="Heading 3"/></w:style></w:styles>')
    before = ET.tostring(root)
    assert normalize_lists(root, styles, numbering(marker),12.5).items == 0
    assert ET.tostring(root) == before


def test_inherited_numbering_and_override_level_are_resolved_without_changing_definitions() -> None:
    root = document(item('first;').replace('<w:numPr><w:ilvl w:val="0"/><w:numId w:val="22"/></w:numPr>', '<w:pStyle w:val="Child"/>')*2)
    styles = xml(f'''<w:styles xmlns:w="{W[1:-1]}"><w:style w:styleId="Child"><w:basedOn w:val="Parent"/></w:style>
    <w:style w:styleId="Parent"><w:pPr><w:numPr><w:numId w:val="22"/></w:numPr></w:pPr></w:style></w:styles>''')
    nums = numbering('%1.%2.')
    override = xml(f'<w:lvlOverride xmlns:w="{W[1:-1]}" w:ilvl="0"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/><w:lvlText w:val="%1)"/></w:lvl></w:lvlOverride>')
    nums.find(W+'num').append(override)
    assert normalize_lists(root, styles, nums,12.5).items == 2


def test_punctuation_is_audited_per_nested_list_without_changing_proper_names_or_abbreviations() -> None:
    root = document('<w:p><w:r><w:t>Intro:</w:t></w:r></w:p>'+item('parent.')+item('nested t.d.;',1)+item('final.',1)+item('final.'))
    before = root.xpath('.//w:t/text()',namespaces=NS)
    report = normalize_lists(root,None,numbering(),12.5)
    assert len(report.warnings) == 1 and '«:»' in report.warnings[0]
    assert root.xpath('.//w:t/text()',namespaces=NS) == before


def test_tables_singletons_field_constructs_and_cancelled_numbering_not_reformatted() -> None:
    for content in (item('only'), '<w:tbl><w:tr><w:tc>'+item('a')+item('b')+'</w:tc></w:tr></w:tbl>',
                    item('a').replace('<w:t', '<w:fldChar w:fldCharType="begin"/><w:t')+item('b'),
                    (item('a')+item('b')).replace('w:val="22"','w:val="0"')):
        root = document(content); before = ET.tostring(root)
        assert normalize_lists(root,None,numbering(),12.5).items == 0
        assert ET.tostring(root) == before


def test_formatter_keeps_numbering_and_all_text_nodes_with_lists_before_main_section(tmp_path: Path) -> None:
    doc = Document()
    doc.add_paragraph('Conditions:')
    doc.add_paragraph('First long list item;','List Bullet')
    doc.add_paragraph('Last item.','List Bullet')
    doc.add_heading('Requirements',1)
    doc.add_paragraph('Technical value: 27.5 V.')
    source, target = tmp_path/'source.docx', tmp_path/'target.docx'
    doc.save(source)
    report = format_docx(source,target)
    assert any('перечислений: 2' in c for c in report.changes)
    with ZipFile(source) as a, ZipFile(target) as b:
        orig, changed = ET.fromstring(a.read('word/numbering.xml')), ET.fromstring(b.read('word/numbering.xml'))
        for level in orig.findall(W+'abstractNum'):
            assert ET.tostring(level) == ET.tostring(changed.find("w:abstractNum[@w:abstractNumId='"+level.get(W+'abstractNumId')+"']",NS))
        assert [n.get(W+'numId') for n in orig.findall(W+'num')] == [n.get(W+'numId') for n in changed.findall(W+'num')]
        assert ET.fromstring(a.read('word/document.xml')).xpath('//w:t/text()',namespaces=NS) == ET.fromstring(b.read('word/document.xml')).xpath('//w:t/text()',namespaces=NS)


def test_body_outline_level_9_does_not_hide_lists() -> None:
    root = document(item('first;',extra='<w:outlineLvl w:val="9"/>')+item('last.',extra='<w:outlineLvl w:val="9"/>'))
    assert normalize_lists(root,None,numbering(),12.5).items == 2


@pytest.mark.skipif(os.environ.get('BUTUZ_DOCUMENTS_LIVE') != '1', reason='Requires prepared local document image')
def test_actual_pdf_wrapped_lines_return_to_each_level_boundary(tmp_path: Path) -> None:
    import io
    import pdfplumber
    from document_runner import prepare_document
    from docx.oxml import OxmlElement
    from docx.shared import Pt
    doc = Document()
    doc.styles['Normal'].font.name = 'Liberation Serif'
    doc.styles['Normal'].font.size = Pt(14)
    doc.add_heading('Requirements',1)
    doc.add_paragraph('Example:')
    defs = numbering()
    defs.find('w:abstractNum/w:lvl/w:numFmt',NS).set(W+'val','lowerLetter')
    defs.find("w:abstractNum/w:lvl[@w:ilvl='1']/w:numFmt",NS).set(W+'val','decimal')
    for index, kind, label in ((2,'lowerRoman','%3)'),(3,'bullet','-')):
        lvl = ET.SubElement(defs.find(W+'abstractNum'),W+'lvl'); lvl.set(W+'ilvl',str(index))
        fmt = ET.SubElement(lvl,W+'numFmt'); fmt.set(W+'val',kind)
        text = ET.SubElement(lvl,W+'lvlText'); text.set(W+'val',label)
    doc.part.numbering_part.element.extend(list(defs))
    sequence = (('Alpha',0),('Beta',1),('Gamma',2),('Delta',3),('Epsilon',3),('Zeta',2),('Eta',1),('Theta',0))
    for word, level in sequence:
        p = doc.add_paragraph(word + ' ' + 'wrapped example words repeated for checking line geometry ' * 2 + '.')
        num = OxmlElement('w:numPr')
        index = OxmlElement('w:ilvl'); index.set(W+'val',str(level)); num.append(index)
        ref = OxmlElement('w:numId'); ref.set(W+'val','22'); num.append(ref)
        p._p.get_or_add_pPr().append(num)
    source = tmp_path/'source.docx'; doc.save(source)
    raw = source.read_bytes()
    c = prepare_document(source)
    assert source.read_bytes() == raw
    words = []
    with pdfplumber.open(io.BytesIO(c.preview_pdf)) as pdf:
        for page in pdf.pages:
            words.extend(page.extract_words())
    # This bounded fixture fits one page. Inspect rendered coordinates, not only
    # DOCX properties: inherited numbering tabs must not win over the recipe.
    assert len(c.pages) == 1
    starts = [next(w for w in words if w['text']==name) for name, _ in sequence]
    for i, first in enumerate(starts):
        following_y = starts[i+1]['top'] if i+1 < len(starts) else 1000
        lines = [w for w in words if first['top']+8 < w['top'] < following_y-2]
        assert lines
        top = min(w['top'] for w in lines)
        continuation = min(w['x0'] for w in lines if abs(w['top']-top)<1)
        base = doc.sections[0].left_margin.pt + sequence[i][1]*709/20
        assert continuation == pytest.approx(base,abs=1)
        assert first['x0'] == pytest.approx(base+1069/20,abs=1)
    assert any(w['text']=='a)' for w in words) and any(w['text']=='i)' for w in words)


def test_false_bidi_is_body_but_actual_rtl_is_protected() -> None:
    for value, expected in (('0',2),('false',2),('1',0)):
        root = document(item('first;',extra=f'<w:bidi w:val="{value}"/>')+item('last.',extra=f'<w:bidi w:val="{value}"/>'))
        assert normalize_lists(root,None,numbering(),12.5).items == expected


def test_shared_table_counter_is_not_changed_by_body_list_layout() -> None:
    root = document(item('first;')+item('last.')+'<w:tbl><w:tr><w:tc>'+item('table')+'</w:tc></w:tr></w:tbl>')
    nums = numbering(); before, definition = ET.tostring(root), ET.tostring(nums)
    report = normalize_lists(root,None,nums,12.5)
    assert report.items == 0 and report.warnings
    assert ET.tostring(root) == before and ET.tostring(nums) == definition
