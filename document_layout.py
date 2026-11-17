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


def normalize_frame_area(document: Any, package: Any, profile: Any) -> int:
    """Reserve body clearance for recognized full-page ESKD header frames.

    Never move drawing anchors. A different-first-page contents stamp needs a
    separate section because Word cannot assign first-page-only body margins.
    Unknown page furniture is left for review, not guessed from text alone.
    """
    import copy
    from pathlib import PurePosixPath

    body = document.find(W + 'body')
    if body is None or 'word/_rels/document.xml.rels' not in package.namelist():
        return 0
    parser = ET.XMLParser(resolve_entities=False, no_network=True)
    relations = ET.fromstring(package.read('word/_rels/document.xml.rels'), parser)
    targets = {r.get('Id'): r.get('Target', '') for r in relations
               if r.get('TargetMode') != 'External'}

    def header(identifier: str) -> Any:
        target = targets.get(identifier, '')
        name = str(PurePosixPath('word') / target)
        if not target or '..' in PurePosixPath(target).parts or name not in package.namelist():
            return None
        return ET.fromstring(package.read(name), parser)

    def framed(root: Any) -> bool:
        if root is None or not any('ТУ' in (t.text or '') for t in root.iter(W + 't')):
            return False
        for anchor in root.findall('.//wp:anchor', NS):
            extent = anchor.find('wp:extent', NS)
            position = anchor.find('wp:positionV', NS)
            if (extent is not None and position is not None and position.get('relativeFrom') in {'page', 'paragraph'}
                    and 6_000_000 <= int(extent.get('cx', '0')) <= 8_000_000
                    and 9_000_000 <= int(extent.get('cy', '0')) <= 11_000_000):
                return True
        return False

    def reserve(section: Any, bottom: int) -> None:
        margins = section.find(W + 'pgMar')
        if margins is not None:
            for side, mm in (('top', profile.frame_top_mm), ('bottom', bottom)):
                margins.set(W + side, str(max(int(margins.get(W + side, '0')), round(mm * 1440 / 25.4))))

    sections = list(document.findall('.//w:sectPr', NS))
    default = first = ''
    start = count = 0
    for section in sections:
        for reference in section.findall(W + 'headerReference'):
            identifier = reference.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id', '')
            if reference.get(W + 'type') == 'default':
                default = identifier
            elif reference.get(W + 'type') == 'first':
                first = identifier
        end_block = section if section.getparent() is body else section.getparent().getparent()
        blocks = list(body)
        end = blocks.index(end_block)
        substantive = any(b.tag in {W+'tbl', W+'sdt'} or b.xpath('.//w:t | .//w:drawing | .//w:pict', namespaces=NS)
                          for b in blocks[start:end+1])
        original_margins = copy.deepcopy(section.find(W+'pgMar'))
        if substantive and framed(header(default)):
            reserve(section, profile.frame_bottom_mm)
            count += 1
            first_header = header(first)
            large_first = (section.find(W + 'titlePg') is not None and framed(first_header)
                           and any((t.text or '').strip() == 'Листов' for t in first_header.iter(W + 't')))
            if large_first:
                contents = [b for b in blocks[start:end] if b.tag == W + 'sdt'
                            and any('TOC ' in (t.text or '') for t in b.iter(W + 'instrText'))]
                if len(contents) == 1:
                    index = blocks.index(contents[0]) + 1
                    spacers: list[Any] = []
                    while index < end and blocks[index].tag == W + 'p' and not ''.join(blocks[index].itertext()).strip():
                        p = blocks[index]
                        if p.xpath('.//w:sectPr | .//w:drawing | .//w:pict | .//w:fldChar', namespaces=NS):
                            break
                        spacers.append(p); index += 1
                    boundary = spacers[-1] if spacers else ET.Element(W + 'p')
                    if not spacers:
                        body.insert(index, boundary)
                    toc_section = copy.deepcopy(section)
                    reserve(toc_section, profile.first_frame_bottom_mm)
                    for p in spacers:
                        for br in p.xpath('.//w:br[@w:type="page"]', namespaces=NS):
                            br.getparent().remove(br)
                        from document_elements import _node, _set
                        _set(_node(p, 'pPr'), 'pageBreakBefore', val='0')
                        _node(_node(p, 'pPr'), 'spacing').attrib.clear()
                        _set(_node(p, 'pPr'), 'spacing', before='0', after='0', line='20', lineRule='exact')
                    from document_elements import _node
                    _node(boundary, 'pPr').append(toc_section)
                    section.remove(section.find(W + 'titlePg'))
                    count += 1
                else:
                    # Without an unambiguous boundary, protect all pages rather
                    # than leave body text able to overlap the larger first stamp.
                    reserve(section, profile.first_frame_bottom_mm)
            # A full-page change-registration grid is an existing form, not
            # prose. Give it its original work area in its own section instead
            # of pushing its last blank rows onto a mostly empty extra page.
            blocks = list(body)
            forms = [b for b in blocks[start:blocks.index(end_block)]
                     if b.tag==W+'p' and ''.join(b.xpath('.//w:t/text()',namespaces=NS)).strip()=='Лист регистрации изменений']
            if len(forms)==1 and original_margins is not None:
                title = forms[0]; index=blocks.index(title)+1
                while index<len(blocks) and blocks[index].tag==W+'p' and not ''.join(blocks[index].xpath('.//w:t/text()',namespaces=NS)).strip():
                    index += 1
                grid = blocks[index] if index<len(blocks) else None
                text = ''.join(grid.xpath('.//w:t/text()',namespaces=NS)) if grid is not None else ''
                trailing = blocks[index+1:blocks.index(end_block)+1]
                if (grid is not None and grid.tag==W+'tbl' and len(grid.findall(W+'tr'))>=10
                        and all(label in text for label in ('Номера листов','Подпись','Дата'))
                        and all(b.tag==W+'p' and not ''.join(b.xpath('.//w:t/text()',namespaces=NS)).strip() for b in trailing)):
                    boundary=title.getprevious()
                    if boundary is None or boundary.tag!=W+'p' or boundary.find('w:pPr/w:sectPr',NS) is not None:
                        boundary=ET.Element(W+'p'); body.insert(blocks.index(title),boundary)
                    from document_elements import _node, _set
                    for br in boundary.xpath('.//w:br[@w:type="page"]',namespaces=NS):
                        br.getparent().remove(br)
                    previous_section=copy.deepcopy(section)
                    _set(previous_section,'type',val='nextPage')
                    _node(boundary,'pPr').append(previous_section)
                    section.replace(section.find(W+'pgMar'),original_margins)
                    _set(section,'type',val='nextPage')
                    count += 1
        start = list(body).index(end_block) + 1
    return count


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
