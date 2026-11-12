"""Portable editable stamp labels and verified pagination caches."""
from __future__ import annotations

import copy
from pathlib import Path
import re
from typing import Any
from zipfile import ZipFile

from lxml import etree as ET  # type: ignore[import-untyped]

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
NS = {'w': W[1:-1], 'wps': 'http://schemas.microsoft.com/office/word/2010/wordprocessingShape',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'}


def sub(parent: Any, tag: str, **attributes: str) -> Any:
    child = ET.SubElement(parent, W + tag)
    for key, value in attributes.items():
        child.set(W + key, value)
    return child


def normalize_stamps(root: Any) -> tuple[int, int, int]:
    """Keep original boxes/coordinates; rotate editable cells inside narrow labels.

    Floating tables in the header would move body content. These tables remain
    INSIDE their existing textboxes, so the header/frame geometry stays intact.
    Both DrawingML and VML text representations receive the same change.
    """
    before = root.xpath('//w:t/text()', namespaces=NS)
    labels: dict[str, set[tuple[int, int]]] = {}
    shapes = root.findall('.//wps:wsp', NS)
    for shape in shapes:
        text = ''.join(shape.xpath('.//w:t/text()', namespaces=NS))
        extent = shape.find('.//a:xfrm/a:ext', NS)
        if extent is None or not text or len(text) > 80:
            continue
        width, height = int(extent.get('cx', '0')), int(extent.get('cy', '0'))
        if 90_000 <= width <= 252_000 and 432_000 <= height <= 2_880_000 and height > width * 3:
            labels.setdefault(text, set()).add((width, height))
    rotated = 0
    for box in root.findall('.//w:txbxContent', NS):
        text = ''.join(box.xpath('.//w:t/text()', namespaces=NS))
        sizes = labels.get(text, set())
        if len(sizes) != 1 or box.find(W + 'tbl') is not None:
            continue
        if any(child.tag != W + 'p' for child in box):
            continue
        width, height = next(iter(sizes))
        paragraphs = [copy.deepcopy(p) for p in box]
        box[:] = []
        table = sub(box, 'tbl'); properties = sub(table, 'tblPr')
        sub(properties, 'tblW', w=str(round(width / 635)), type='dxa')
        borders = sub(properties, 'tblBorders')
        for tag in ('top', 'bottom', 'left', 'right', 'insideH', 'insideV'):
            sub(borders, tag, val='nil')
        sub(properties, 'tblLayout', type='fixed')
        margins = sub(properties, 'tblCellMar')
        for tag in ('top', 'bottom', 'left', 'right'):
            sub(margins, tag, w='0', type='dxa')
        grid = sub(table, 'tblGrid'); sub(grid, 'gridCol', w=str(round(width / 635)))
        row = sub(table, 'tr'); row_properties = sub(row, 'trPr')
        sub(row_properties, 'trHeight', val=str(round(height / 635) - 20), hRule='exact')
        cell = sub(row, 'tc'); cell_properties = sub(cell, 'tcPr')
        sub(cell_properties, 'tcW', w=str(round(width / 635)), type='dxa')
        sub(cell_properties, 'textDirection', val='btLr'); sub(cell_properties, 'vAlign', val='center')
        for paragraph in paragraphs:
            previous = paragraph.find(W + 'pPr')
            if previous is not None:
                paragraph.remove(previous)
            ppr = ET.Element(W + 'pPr'); paragraph.insert(0, ppr)
            sub(ppr, 'spacing', before='0', after='0', line='240', lineRule='auto')
            sub(ppr, 'jc', val='center'); cell.append(paragraph)
        rotated += 1
    resized = 0
    for box in root.findall('.//w:txbxContent', NS):
        text = ''.join(box.xpath('.//w:t/text()', namespaces=NS))
        if re.fullmatch(r'\d{2}\.\d{2}\.\d{2}(?:\d{2})?', text):
            for run in box.findall('.//w:r', NS):
                pr = run.find(W + 'rPr')
                if pr is None:
                    pr = ET.Element(W + 'rPr'); run.insert(0, pr)
                for tag in ('sz', 'szCs'):
                    node = pr.find(W + tag)
                    if node is None:
                        node = sub(pr, tag)
                    node.set(W + 'val', '15')
                fonts = pr.find(W + 'rFonts')
                if fonts is None:
                    fonts = ET.Element(W + 'rFonts'); pr.insert(0, fonts)
                for attribute in ('ascii', 'hAnsi', 'cs'):
                    fonts.set(W + attribute, 'Times New Roman')
            resized += 1
    # Recognize the page-count box by its geometric relation to "Листов".
    # Do not replace arbitrary occurrences of a number in technical data.
    counts: set[str] = set()
    headers = [s for s in shapes if ''.join(s.xpath('.//w:t/text()', namespaces=NS)).strip() == 'Листов']
    for header in headers:
        offset = header.find('.//a:xfrm/a:off', NS)
        if offset is None:
            continue
        hx, hy = int(offset.get('x')), int(offset.get('y'))
        for shape in shapes:
            text = ''.join(shape.xpath('.//w:t/text()', namespaces=NS)).strip()
            at = shape.find('.//a:xfrm/a:off', NS)
            if text.isdigit() and at is not None:
                dx, dy = abs(int(at.get('x')) - hx), int(at.get('y')) - hy
                if dx < 18_000 and 0 < dy < 360_000:
                    counts.add(text)
    field_count = 0
    # Repeated numeric metadata must never be guessed to mean a page count.
    counts = {value for value in counts if sum(
        ''.join(box.xpath('.//w:t/text()', namespaces=NS)).strip() == value
        for box in root.findall('.//w:txbxContent', NS)) <= 2}
    for box in root.findall('.//w:txbxContent', NS):
        text = ''.join(box.xpath('.//w:t/text()', namespaces=NS)).strip()
        if text not in counts or box.find('.//w:fldChar', NS) is not None:
            continue
        paragraph = box.find(W + 'p')
        if paragraph is None:
            continue
        runs = list(paragraph.findall(W + 'r'))
        if not runs:
            continue
        position = list(paragraph).index(runs[0])
        begin = ET.Element(W + 'r'); sub(begin, 'fldChar', fldCharType='begin')
        instruction = ET.Element(W + 'r'); node = sub(instruction, 'instrText'); node.text = ' NUMPAGES '
        separate = ET.Element(W + 'r'); sub(separate, 'fldChar', fldCharType='separate')
        for node in reversed([begin, instruction, separate]):
            paragraph.insert(position, node)
        end = sub(paragraph, 'r'); sub(end, 'fldChar', fldCharType='end')
        field_count += 1
    # Some legacy PAGE boxes are only one digit wide. Keep their anchor, but
    # reserve enough space for the supported two-digit page range (<=60 pages).
    for box in root.findall('.//w:txbxContent', NS):
        if not any((node.text or '').strip() == 'PAGE' for node in box.findall('.//w:instrText', NS)):
            continue
        for parent in box.iterancestors():
            if parent.tag == '{' + NS['wps'] + '}wsp':
                extent = parent.find('./wps:spPr/a:xfrm/a:ext', NS)
                if extent is not None and int(extent.get('cx', '0')) < 254_000:
                    extent.set('cx', '254000')
                    anchors = list(parent.iterancestors('{' + NS['wp'] + '}anchor'))
                    if anchors:
                        outer = anchors[0].find('wp:extent', NS)
                        if outer is not None:
                            outer.set('cx', '254000')
                    field_count += 1
            if parent.tag == '{urn:schemas-microsoft-com:vml}rect':
                style = parent.get('style', '')
                match = re.search(r'(?:^|;)width:([\d.]+)pt', style)
                if match and float(match.group(1)) < 20:
                    parent.set('style', re.sub(r'(?<=;)width:[\d.]+pt', 'width:20pt', ';' + style).lstrip(';'))
                    field_count += 1
    if root.xpath('//w:t/text()', namespaces=NS) != before:
        raise ValueError('Изменился текст штампа; обработка остановлена')
    return rotated, resized, field_count


def refresh_pagination(path: Path, pdf: Path) -> tuple[int, int]:
    """Only update cached TOC page numbers via bookmark targets and rendered headings."""
    import pdfplumber
    with pdfplumber.open(pdf) as rendered:
        bold = [''.join(c['text'] for c in page.chars if 'bold' in c['fontname'].lower()) for page in rendered.pages]
        count = len(rendered.pages)
    def normalize(text: str) -> str:
        return re.sub(r'\s+', '', text).casefold()
    pages = [normalize(text) for text in bold]
    updates: dict[str, bytes] = {}
    changed = unresolved = 0
    with ZipFile(path) as package:
        document = ET.fromstring(package.read('word/document.xml'))
        bookmarks = {n.get(W + 'name'): n for n in document.findall('.//w:bookmarkStart', NS)}
        cursor = 1  # A TOC target must occur after the first page; titles are not TOC entries.
        for sdt in document.findall('.//w:sdt', NS):
            if not sdt.xpath('.//w:docPartGallery[@w:val="Table of Contents"]', namespaces=NS):
                continue
            for link in sdt.findall('.//w:hyperlink', NS):
                cache = link.findall('.//w:t', NS)
                target = bookmarks.get(link.get(W + 'anchor'))
                if target is None or not cache or not (cache[-1].text or '').isdigit():
                    unresolved += 1; continue
                paragraphs = list(target.iterancestors(W + 'p'))
                if not paragraphs:
                    unresolved += 1; continue
                title = normalize(''.join(paragraphs[0].xpath('.//w:t/text()', namespaces=NS)))
                matches = [n for n in range(cursor, count) if title and title in pages[n]]
                if not matches:
                    unresolved += 1; continue
                cursor = matches[0]
                value = str(cursor + 1)
                if cache[-1].text != value:
                    cache[-1].text = value; changed += 1
        updates['word/document.xml'] = ET.tostring(document, xml_declaration=True, encoding='UTF-8', standalone=True)
        temporary = path.with_suffix('.pagination.docx')
        with ZipFile(temporary, 'w') as result:
            for item in package.infolist():
                data = package.read(item.filename)
                if item.filename.startswith(('word/header', 'word/footer')) and item.filename.endswith('.xml'):
                    root = ET.fromstring(data)
                    for instruction in root.findall('.//w:instrText', NS):
                        if (instruction.text or '').strip() == 'NUMPAGES':
                            run = instruction.getparent()
                            parent = run.getparent()
                            after = list(parent)[list(parent).index(run)+1:]
                            for next_run in after:
                                text = next_run.find(W + 't')
                                if text is not None:
                                    text.text = str(count); break
                    data = ET.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
                result.writestr(copy.copy(item), updates.get(item.filename, data))
    temporary.replace(path)
    return changed, unresolved
