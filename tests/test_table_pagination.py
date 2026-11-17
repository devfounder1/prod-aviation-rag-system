from __future__ import annotations

import copy
import io
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.shared import Pt
from lxml import etree as ET
import pytest

from document_elements import W, NS, normalize_elements
from gost_formatter import format_docx
from standard_profiles import load_profile
from document_layout import normalize_frame_area
from table_pagination import (RowBox, _header_key, flows, merge_manual_parts,
                              measure, pack_rows, probe, split_tables, verify_chunks)


def fixture() -> object:
    doc = Document(); doc.add_heading('Requirements', 1); doc.add_paragraph('Таблица 7')
    table = doc.add_table(rows=5, cols=2)
    table.cell(0,0).text = 'Наименование'; table.cell(0,1).text = 'Значение'
    for i in range(1,5):
        table.cell(i,0).text = f'Record {i}'
        table.cell(i,1).text = f'{i}.001'
    root = ET.fromstring(ET.tostring(doc._element)); normalize_elements(root,12)
    return root


def test_body_keeps_one_and_half_line_without_old_paragraph_gaps(tmp_path: Path) -> None:
    doc = Document(); doc.add_heading('Section one',1)
    body = doc.add_paragraph('Prose'); body.paragraph_format.space_before = Pt(45)
    body.paragraph_format.space_after = Pt(24)
    spacing = body._p.get_or_add_pPr().find(W+'spacing')
    for key,value in [('beforeAutospacing','1'),('afterAutospacing','1'),('beforeLines','800')]:
        spacing.set(W+key,value)
    doc.add_heading('Numbered prose',3)
    doc.add_heading('Section two',1)
    source,target = tmp_path/'a.docx',tmp_path/'b.docx'
    doc.save(source); format_docx(source,target)
    result = Document(target)
    assert load_profile().body_line == 1.5
    for p in result.paragraphs[1:3]:
        s = p._p.find('w:pPr/w:spacing',NS)
        assert s.attrib == {W+'before':'0',W+'after':'0',W+'line':'360',W+'lineRule':'auto'}
        assert p._p.find('w:pPr/w:snapToGrid',NS).get(W+'val') == '0'
    assert result.paragraphs[0].paragraph_format.page_break_before
    assert result.paragraphs[3].paragraph_format.page_break_before is False


def test_row_packing_keeps_short_note_with_record_and_rejects_oversized_group() -> None:
    assert pack_rows([40,40,40,15],90,100,keep_last=True) == [[0,1],[2,3]]
    with pytest.raises(ValueError,match='не помещается'):
        pack_rows([120],80,100,keep_last=False)


def test_split_adds_caption_above_each_part_but_preserves_data_rows() -> None:
    root = fixture(); original = copy.deepcopy(root)
    f = flows(root)[0]
    original_rows = f.table.findall(W+'tr')[1:]
    keys = _header_key(original_rows)
    boxes = {(0,i):[RowBox(0,100+i*120,100+(i+1)*120)] for i in range(5)}
    assert split_tables(root,boxes,10) == 1
    parts = flows(root)
    assert len(parts) == 2
    assert parts[1].caption.xpath('.//w:t/text()',namespaces=NS) == ['Продолжение таблицы 7']
    assert parts[1].caption.find('w:pPr/w:pageBreakBefore',NS).get(W+'val') == '1'
    after_rows = [r for p in parts for r in p.table.findall(W+'tr')[p.headers:]]
    assert after_rows == original_rows  # moved nodes, not regenerated technical content
    assert _header_key(after_rows) == keys
    assert root.xpath('.//w:t[contains(text(),"ZZBT")]',namespaces=NS) == []
    first_header = original.find('w:body/w:tbl/w:tr',NS)
    assert _header_key([first_header]) == _header_key([parts[1].table.findall(W+'tr')[0]])


def test_verification_detects_unlabelled_automatic_spill_or_missing_row() -> None:
    root = fixture()
    one_page = {(0,i):[RowBox(0,80+i*30,110+i*30)] for i in range(5)}
    assert verify_chunks(root,one_page)
    spill = copy.deepcopy(one_page); spill[(0,4)] = [RowBox(1,100,130)]
    assert not verify_chunks(root,spill)
    del one_page[(0,2)]
    assert not verify_chunks(root,one_page)


def test_measure_uses_row_rules_inside_full_page_frame(tmp_path: Path) -> None:
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

    writer=PdfWriter(); page=writer.add_blank_page(600,800)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),
                           NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    commands=['0.5 w 20 20 560 760 re S']
    for y in (700,650,600,550):
        commands.append(f'50 {y} m 550 {y} l S')
    for i,y in enumerate((680,630,580)):
        commands.append(f'BT /F1 1 Tf 1 1 1 rg 60 {y} Td (ZZBT00R{i:04}ZZ) Tj ET')
    stream=DecodedStreamObject();stream.set_data(('\n'.join(commands)).encode())
    page[NameObject('/Contents')]=writer._add_object(stream)
    path=tmp_path/'rows.pdf'
    with path.open('wb') as out:
        writer.write(out)
    boxes=measure(path)
    assert boxes=={(0,i):[RowBox(0,100+i*50,150+i*50)] for i in range(3)}


def test_manual_parts_merge_only_when_furniture_and_boundary_are_proven() -> None:
    # Reproduce normalize_elements' old caption-row continuation layout.
    doc = Document(); doc.add_paragraph('Таблица 7')
    a = doc.add_table(rows=2,cols=2); a.cell(0,0).text='Наименование'; a.cell(0,1).text='Значение'
    a.cell(1,0).text='Record A'; a.cell(1,1).text='0.001'
    doc.add_paragraph('Продолжение таблицы 7')
    b = doc.add_table(rows=2,cols=2); b.cell(0,0).text='Наименование'; b.cell(0,1).text='Значение'
    b.cell(1,0).text='Record B'; b.cell(1,1).text='27.5'
    tree = ET.fromstring(ET.tostring(doc._element)); normalize_elements(tree,12)
    differing = copy.deepcopy(tree)
    last = differing.find('w:body',NS).findall(W+'tbl')[1]
    last.findall(W+'tr')[1].find('.//w:t',NS).text='Other meaning'
    assert merge_manual_parts(differing)==0
    assert merge_manual_parts(tree)==1
    tables = tree.find('w:body',NS).findall(W+'tbl')
    assert len(tables)==1
    assert [''.join(r.xpath('.//w:t/text()',namespaces=NS)) for r in tables[0].findall(W+'tr')[1:]] == ['Record A0.001','Record B27.5']
    assert not any('Продолжение' in t for t in tree.xpath('.//w:t/text()',namespaces=NS))


def test_probe_never_changes_candidate_or_unrelated_package_parts(tmp_path: Path) -> None:
    doc=Document(); doc.add_heading('Section',1); doc.add_paragraph('Таблица 1')
    table=doc.add_table(rows=2,cols=2)
    table.cell(0,0).text='Наименование'; table.cell(0,1).text='Значение'; table.cell(1,0).text='Data'
    source,target,analysis=tmp_path/'source.docx',tmp_path/'target.docx',tmp_path/'probe.docx'
    doc.save(source); format_docx(source,target)
    raw=target.read_bytes(); tree=ET.fromstring(ZipFile(target).read('word/document.xml'))
    xml=ET.tostring(tree); probe(target,analysis,tree)
    assert target.read_bytes()==raw and ET.tostring(tree)==xml
    with ZipFile(analysis) as z,ZipFile(target) as original:
        assert b'ZZBT' in z.read('word/document.xml')
        assert all(z.read(n)==original.read(n) for n in original.namelist() if n!='word/document.xml')


def test_frame_clearance_separates_contents_and_fixed_form_without_changing_header() -> None:
    rel='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    wp='http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
    header=f'''<w:hdr xmlns:w="{W[1:-1]}" xmlns:wp="{wp}"><w:p><w:r><w:t>TEST.001 ТУ</w:t>
      <w:drawing><wp:anchor><wp:positionV relativeFrom="paragraph"><wp:posOffset>210000</wp:posOffset></wp:positionV>
      <wp:extent cx="7056000" cy="10262880"/></wp:anchor></w:drawing></w:r></w:p></w:hdr>'''
    first=header.replace('</w:hdr>','<w:p><w:r><w:t>Листов</w:t></w:r></w:p></w:hdr>')
    root=ET.fromstring(f'''<w:document xmlns:w="{W[1:-1]}" xmlns:r="{rel}"><w:body>
      <w:p><w:r><w:t>Содержание</w:t></w:r></w:p>
      <w:sdt><w:sdtContent><w:p><w:r><w:instrText> TOC </w:instrText></w:r></w:p></w:sdtContent></w:sdt>
      <w:p><w:r><w:br w:type="page"/></w:r></w:p>
      <w:p><w:r><w:t>Ordinary prose</w:t></w:r></w:p>
      <w:p><w:r><w:t>Figure caption</w:t><w:br w:type="page"/></w:r></w:p>
      <w:p><w:r><w:t>Лист регистрации изменений</w:t></w:r></w:p>
      <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Номера листов Подпись Дата</w:t></w:r></w:p></w:tc></w:tr>
      {''.join('<w:tr><w:tc><w:p/></w:tc></w:tr>' for _ in range(10))}</w:tbl>
      <w:p><w:pPr><w:sectPr><w:headerReference w:type="default" r:id="h"/>
      <w:headerReference w:type="first" r:id="f"/><w:type w:val="nextPage"/>
      <w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="425" w:bottom="1276" w:left="1701" w:right="794"/>
      <w:titlePg/></w:sectPr></w:pPr></w:p>
      <w:sectPr><w:type w:val="continuous"/><w:pgMar w:top="425" w:bottom="1276"/></w:sectPr>
      </w:body></w:document>''')
    raw=io.BytesIO()
    with ZipFile(raw,'w') as z:
        z.writestr('word/header1.xml',header);z.writestr('word/header2.xml',first)
        z.writestr('word/_rels/document.xml.rels', '<Relationships><Relationship Id="h" Target="header1.xml"/>'
                   '<Relationship Id="f" Target="header2.xml"/></Relationships>')
    before=root.xpath('.//w:t/text()',namespaces=NS)
    with ZipFile(raw) as z:
        assert normalize_frame_area(root,z,load_profile())==3
        assert z.read('word/header1.xml')==header.encode()
    sections=root.findall('.//w:sectPr',NS)
    assert len(sections)==4
    margins=[s.find(W+'pgMar') for s in sections]
    assert [int(m.get(W+'bottom')) for m in margins]==[3231,1984,1276,1276]
    assert root.xpath('.//w:t/text()',namespaces=NS)==before
    assert not root.xpath('.//w:br[@w:type="page"]',namespaces=NS)
    assert len(root.xpath('.//w:pPr/w:pPr',namespaces=NS))==0


def test_numbered_note_has_space_for_its_right_aligned_label_inside_border() -> None:
    doc=Document();doc.add_paragraph('Таблица 1');table=doc.add_table(rows=3,cols=2)
    table.cell(0,0).text='Наименование';table.cell(0,1).text='Значение'
    table.cell(1,0).text='Record';table.cell(1,1).text='27.5'
    note=table.cell(2,0).merge(table.cell(2,1));note.text='Примечания'
    p=note.add_paragraph('Original numbered note')
    num=ET.SubElement(p._p.get_or_add_pPr(),W+'numPr')
    ET.SubElement(num,W+'numId').set(W+'val','1')
    tree=ET.fromstring(ET.tostring(doc._element));before=tree.xpath('.//w:t/text()',namespaces=NS)
    normalize_elements(tree,12)
    indent=tree.find('w:body/w:tbl/w:tr[3]/w:tc/w:p[2]/w:pPr/w:ind',NS)
    assert int(indent.get(W+'left'))-int(indent.get(W+'hanging'))>=180
    assert tree.xpath('.//w:t/text()',namespaces=NS)==before
