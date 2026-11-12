from __future__ import annotations

import copy
import io
from pathlib import Path
import struct
from zipfile import ZipFile

from docx import Document
from lxml import etree as ET
from PIL import Image
import pytest

from gost_formatter import format_docx
from metafile_layout import FontRepair, UnsupportedMetafile, repair_emf


def metafile() -> tuple[bytes, int, int]:
    header = bytearray(88)
    struct.pack_into('<II', header, 0, 1, 88)
    header[40:44] = b' EMF'
    struct.pack_into('<I', header, 44, 0x10000)
    struct.pack_into('<H', header, 56, 3)
    font = bytearray(368)
    struct.pack_into('<IIIiiiii', font, 0, 82, 368, 1, 17, 0, 0, 0, 400)
    font[40:104] = 'GOST'.encode('utf-16-le').ljust(64, b'\0')
    select = struct.pack('<III', 37, 12, 1)
    # Selecting a pen must not deselect the current text font.
    pen = struct.pack('<IIIIiiI', 38, 28, 2, 0, 1, 0, 0)
    select_pen = struct.pack('<III', 37, 12, 2)
    text = 'Тест'.encode('utf-16-le')
    output = bytearray(76 + len(text) + 16)
    struct.pack_into('<II', output, 0, 84, len(output))
    struct.pack_into('<I', output, 24, 1)
    struct.pack_into('<ff', output, 28, 1, 1)
    struct.pack_into('<III', output, 44, 4, 76, 0)
    struct.pack_into('<I', output, 72, 76 + len(text))
    output[76:76+len(text)] = text
    struct.pack_into('<iiii', output, 76 + len(text), 6, 6, 6, 6)
    line = struct.pack('<IIii', 54, 16, 40, 50)
    end = struct.pack('<IIIII', 14, 20, 0, 0, 20)
    records = [header, font, select, pen, select_pen, output, line, end]
    struct.pack_into('<II', header, 48, sum(map(len, records)), len(records))
    return b''.join(records), len(header), sum(map(len, records[:5]))


def test_font_copy_changes_only_font_metrics_and_spacing_pointer() -> None:
    raw, font_at, text_at = metafile()
    result = repair_emf(raw)
    assert isinstance(result, FontRepair)
    assert result.fonts == result.text_runs == 1
    assert len(result.data) == len(raw)
    allowed = set(range(font_at + 16, font_at + 20)) | set(range(font_at + 40, font_at + 104)) | set(range(text_at + 72, text_at + 76))
    assert all(index in allowed for index, (a,b) in enumerate(zip(raw,result.data)) if a != b)
    assert result.data[text_at+76:] == raw[text_at+76:]  # strings, DX data and all following geometry
    assert struct.unpack_from('<i',result.data,font_at+16)[0] == 6
    assert struct.unpack_from('<I',result.data,text_at+72)[0] == 0
    assert repair_emf(result.data) is None


@pytest.mark.parametrize('damage', ['size', 'count', 'offset', 'flags', 'rotation', 'command', 'unicode'])
def test_unsafe_metafile_is_rejected_without_a_partial_repair(damage: str) -> None:
    raw, font_at, text_at = metafile(); data = bytearray(raw)
    if damage == 'size':
        struct.pack_into('<I',data,48,len(data)+4)
    elif damage == 'count':
        struct.pack_into('<I',data,52,9000)
    elif damage == 'offset':
        struct.pack_into('<I',data,text_at+72,0xfffffff0)
    elif damage == 'flags':
        struct.pack_into('<I',data,text_at+52,0x10)  # glyph indexes are not Unicode labels
    elif damage == 'rotation':
        struct.pack_into('<i',data,font_at+20,900)
    elif damage == 'command':
        struct.pack_into('<I',data,font_at+368,35)  # unsupported world transform
    else:
        data[text_at+76:text_at+78]=b'\x00\xd8'
    with pytest.raises(UnsupportedMetafile):
        repair_emf(bytes(data))
    assert raw == metafile()[0]


def test_ordinary_images_and_fonts_are_not_changed() -> None:
    assert repair_emf(b'ordinary image') is None
    raw, font_at, _ = metafile(); data=bytearray(raw)
    data[font_at+40:font_at+104]='Arial'.encode('utf-16-le').ljust(64,b'\0')
    assert repair_emf(bytes(data)) is None


def test_docx_retains_original_metafile_and_adds_only_a_derived_display_part(tmp_path: Path) -> None:
    doc = Document(); doc.add_heading('Requirements',level=1)
    image=io.BytesIO();Image.new('RGB',(20,20),'white').save(image,format='PNG');image.seek(0)
    doc.add_paragraph().add_run().add_picture(image)
    doc.add_paragraph('Рисунок 1 — Проверка')
    placeholder=tmp_path/'placeholder.docx';doc.save(placeholder)
    source, target=tmp_path/'source.docx',tmp_path/'target.docx'
    raw,_,_=metafile()
    rel='http://schemas.openxmlformats.org/package/2006/relationships'
    ct='http://schemas.openxmlformats.org/package/2006/content-types'
    with ZipFile(placeholder) as z, ZipFile(source,'w') as result:
        for entry in z.infolist():
            value=z.read(entry.filename)
            if entry.filename=='word/media/image1.png':
                result.writestr('word/media/image1.emf',raw);continue
            if entry.filename=='word/_rels/document.xml.rels':
                root=ET.fromstring(value)
                for node in root.findall('{'+rel+'}Relationship'):
                    if node.get('Target')=='media/image1.png':node.set('Target','media/image1.emf')
                value=ET.tostring(root)
            if entry.filename=='[Content_Types].xml':
                root=ET.fromstring(value)
                ET.SubElement(root,'{'+ct+'}Default',Extension='emf',ContentType='image/x-emf')
                value=ET.tostring(root)
            result.writestr(copy.copy(entry),value)
    before=source.read_bytes();report=format_docx(source,target)
    assert source.read_bytes()==before
    assert any('шрифт GOST заменён' in warning for warning in report.warnings)
    with ZipFile(source) as a, ZipFile(target) as b:
        assert b.read('word/media/image1.emf')==raw
        additions=set(b.namelist())-set(a.namelist())
        assert len(additions)==1
        derived=additions.pop()
        assert derived.startswith('word/media/butuz-font-') and b.read(derived)!=raw
        assert b'media/image1.emf' in b.read('word/_rels/document.xml.rels')
        assert derived[5:].encode() in b.read('word/_rels/document.xml.rels')
