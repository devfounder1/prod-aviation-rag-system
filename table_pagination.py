"""Render-measured pagination of flat, captioned tables in disposable copies.

Only duplicate furniture may be replaced. Original data rows, numbering and
merges move as complete XML subtrees. Probe labels exist only in analysis copies;
the approved document has ordinary editable captions and tables, without labels.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Callable
from zipfile import ZipFile

from lxml import etree as ET  # type: ignore[import-untyped]

from document_elements import W, NS, TABLE, _header_rows, _integer, _node, _paragraph, _set, _text

Converter = Callable[[Path, Path, str], Path]
TOKEN = re.compile(r'ZZBT\d{2}R\d{4}ZZ')


@dataclass
class TableFlow:
    table: Any
    caption: Any
    number: str
    headers: int
    top: float
    bottom: float


@dataclass(frozen=True)
class RowBox:
    page: int
    top: float
    bottom: float


def _text_nodes(root: Any) -> list[Any]:
    return list(root.xpath('.//w:t | .//w:instrText | .//w:delText', namespaces=NS))


def _check_text(root: Any, original: list[Any], discarded: set[Any], generated: set[Any]) -> None:
    expected = [n for n in original if n not in discarded]
    actual = [n for n in _text_nodes(root) if n not in generated]
    if actual != expected:
        raise ValueError('Изменился порядок или состав исходного текста таблиц; документ не публикуется')


def _save(template: Path, target: Path, root: Any) -> None:
    xml = ET.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
    with ZipFile(template) as source, ZipFile(target, 'w') as out:
        for entry in source.infolist():
            out.writestr(copy.copy(entry), xml if entry.filename == 'word/document.xml' else source.read(entry.filename))


def _read(path: Path) -> Any:
    with ZipFile(path) as package:
        return ET.fromstring(package.read('word/document.xml'), ET.XMLParser(resolve_entities=False, no_network=True))


def _header_key(rows: list[Any]) -> tuple[Any, ...]:
    # Fonts/widths may differ slightly between imported manual parts, but text,
    # column spans and vertical merges must match exactly before deduplication.
    return tuple(tuple((tuple((n.tag, n.text or '') for n in _text_nodes(c)),
                        _integer(c.find('w:tcPr/w:gridSpan', NS), 'val', 1),
                        None if c.find('w:tcPr/w:vMerge', NS) is None else
                        c.find('w:tcPr/w:vMerge', NS).get(W + 'val', 'continue'))
                       for c in r.findall(W + 'tc')) for r in rows)


def _caption_before(body: Any, table: Any) -> Any:
    blocks = list(body)
    index = blocks.index(table) - 1
    while index >= 0 and blocks[index].tag == W + 'p' and not _text(blocks[index]):
        if blocks[index].xpath('.//w:sectPr | .//w:fldChar | .//w:drawing | .//w:bookmarkStart', namespaces=NS):
            return None
        index -= 1
    return blocks[index] if index >= 0 and blocks[index].tag == W + 'p' and TABLE.match(_text(blocks[index])) else None


def merge_manual_parts(root: Any) -> int:
    """Deduplicate proven continuation furniture, never ordinary table values."""
    body = root.find(W + 'body')
    if body is None:
        return 0
    original = _text_nodes(root)
    discarded: set[Any] = set()
    merged = 0
    previous: Any = None
    number = ''
    for block in list(body):
        if block.tag != W + 'tbl':
            if block.tag != W + 'p' or _text(block) or block.xpath(
                    './/w:sectPr | .//w:fldChar | .//w:drawing | .//w:pict | .//w:bookmarkStart', namespaces=NS):
                previous = None
            continue
        rows = block.findall(W + 'tr')
        headers = _header_rows(rows) if rows else 0
        caption = _caption_before(body, block)
        if caption is not None and not _text(caption).lower().startswith('продолжение'):
            match = TABLE.match(_text(caption)); assert match is not None
            previous, number = block, match.group(1).upper()
            continue
        # normalize_elements has put a verified manual caption in a header row.
        label = _text(rows[0]) if rows else ''
        match = re.fullmatch(r'Продолжение\s+таблицы\s+(' + r'[А-ЯA-Zа-яa-z]?\.?\d+(?:\.\d+)*' + r')', label, re.I)
        if previous is None or match is None or match.group(1).upper() != number or headers < 2:
            previous = None
            continue
        old_rows = previous.findall(W + 'tr')
        old_headers = _header_rows(old_rows)
        furniture = rows[:headers]
        if (not old_headers or _header_key(old_rows[:old_headers]) != _header_key(furniture[1:])
                or block.xpath('.//w:tbl | .//w:drawing | .//w:pict | .//w:object | ./w:tblPr/w:tblpPr', namespaces=NS)
                or any(r.xpath('.//w:bookmarkStart | .//w:bookmarkEnd | .//w:fldChar', namespaces=NS) for r in furniture)):
            previous = None
            continue
        widths = [_integer(c, 'w') for c in previous.findall('w:tblGrid/w:gridCol', NS)]
        other = [_integer(c, 'w') for c in block.findall('w:tblGrid/w:gridCol', NS)]
        if len(widths) != len(other) or any(abs(a-b) > max(a,b) * .08 for a,b in zip(widths,other)):
            previous = None
            continue
        discarded.update(n for r in furniture for n in _text_nodes(r))
        for row in rows[headers:]:
            column = _integer(row.find('w:trPr/w:gridBefore', NS), 'val')
            for cell in row.findall(W + 'tc'):
                span = _integer(cell.find('w:tcPr/w:gridSpan', NS), 'val', 1)
                _set(_node(cell, 'tcPr'), 'tcW', w=str(sum(widths[column:column+span])), type='dxa')
                column += span
            previous.append(row)
        body.remove(block)
        merged += 1
    _check_text(root, original, discarded, set())
    return merged


def flows(root: Any) -> list[TableFlow]:
    body = root.find(W + 'body')
    result: list[TableFlow] = []
    if body is None:
        return result
    for table in body.findall(W + 'tbl'):
        caption = _caption_before(body, table)
        rows = table.findall(W + 'tr')
        headers = _header_rows(rows) if rows else 0
        if caption is None or not headers:
            continue
        if (table.xpath('.//w:tbl | .//w:drawing | .//w:pict | .//w:object | ./w:tblPr/w:tblpPr', namespaces=NS)
                or any(r.xpath('.//w:fldChar | .//w:bookmarkStart | .//w:bookmarkEnd', namespaces=NS) for r in rows[:headers])
                or any(r.xpath('./w:tc/w:tcPr/w:vMerge', namespaces=NS) for r in rows[headers:])
                or any(r.find('w:trPr/w:cantSplit', NS) is None
                       or r.find('w:trPr/w:cantSplit', NS).get(W+'val') != '1' for r in rows[headers:])):
            continue
        section = None
        blocks = list(body)
        for block in blocks[blocks.index(table):]:
            section = block if block.tag == W + 'sectPr' else block.find('w:pPr/w:sectPr', NS)
            if section is not None:
                break
        if section is None:
            continue
        margins, size = section.find(W+'pgMar'), section.find(W+'pgSz')
        top = _integer(margins,'top',1440) / 20
        bottom = (_integer(size,'h',16838) - _integer(margins,'bottom',1440)) / 20
        match = TABLE.match(_text(caption)); assert match is not None
        result.append(TableFlow(table, caption, match.group(1), headers, top, bottom))
    if len(result) > 60 or sum(len(f.table.findall(W+'tr')) for f in result) > 2000:
        raise ValueError('Превышен предел постраничной проверки таблиц')
    return result


def probe(template: Path, target: Path, root: Any) -> None:
    """Put small white row IDs only in a disposable measurement copy."""
    candidate = copy.deepcopy(root)
    if TOKEN.search(''.join(n.text or '' for n in _text_nodes(candidate))):
        raise ValueError('Исходный текст совпал со служебными метками анализа')
    for t_index, flow in enumerate(flows(candidate)):
        # Borderless tables still need measurable row bounds. These fine guide
        # lines exist only in the probe and never enter the delivered document.
        if not flow.table.xpath('./w:tblPr/w:tblBorders/*[not(@w:val="nil" or @w:val="none")]', namespaces=NS):
            borders = _node(_node(flow.table,'tblPr'),'tblBorders')
            for side in ('top','bottom','insideH'):
                _set(borders,side,val='single',sz='2',color='000000')
        for r_index, row in enumerate(flow.table.findall(W+'tr')):
            cells = row.findall(W+'tc')
            cell = next((c for c in cells if c.find('w:tcPr/w:vMerge', NS) is None), cells[0])
            paragraphs = cell.findall(W+'p')
            paragraph = paragraphs[-1] if paragraphs else ET.SubElement(cell,W+'p')
            run = ET.SubElement(paragraph,W+'r')
            _set(_node(run,'rPr'),'sz',val='2'); _set(_node(run,'rPr'),'szCs',val='2')
            _set(_node(run,'rPr'),'color',val='FFFFFF')
            text = ET.SubElement(run,W+'t'); text.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
            text.text = f' ZZBT{t_index:02}R{r_index:04}ZZ '
    _save(template,target,candidate)


def measure(pdf: Path) -> dict[tuple[int,int], list[RowBox]]:
    import pdfplumber

    result: dict[tuple[int,int],list[RowBox]] = {}
    with pdfplumber.open(pdf) as document:
        if len(document.pages) > 60:
            raise ValueError('Постраничная проверка поддерживает до 60 страниц')
        for page_index,page in enumerate(document.pages):
            hits = page.search(TOKEN.pattern)
            if not hits:
                continue
            for hit in hits:
                token = hit['text']; key = (int(token[4:6]),int(token[7:11]))
                x = (hit['x0']+hit['x1'])/2
                # A full-page frame can confuse generic table detectors into
                # treating the first data column as one huge merged cell. Use
                # actual ruling segments crossing this probe's x coordinate.
                edges = [float(e['top']) for e in page.horizontal_edges
                         if e['x0']-.5 <= x <= e['x1']+.5 and e['x1']-e['x0'] >= 8]
                above = [v for v in edges if v <= hit['top']+.5]
                below = [v for v in edges if v >= hit['bottom']-.5]
                if not above or not below or min(below)-max(above)<1:
                    raise ValueError('Не удалось измерить границы строки таблицы; документ не публикуется')
                result.setdefault(key,[]).append(RowBox(page_index,max(above),min(below)))
    return result


def pack_rows(heights: list[float], first: float, following: float, *, keep_last: bool) -> list[list[int]]:
    """Pack measured whole rows; keep a final short note with its record."""
    groups = [[index] for index in range(len(heights))]
    if keep_last and len(groups) > 1:
        groups[-2].extend(groups.pop())
    chunks: list[list[int]] = [[]]
    used, available = 0.,first
    for group in groups:
        height = sum(heights[index] for index in group)
        if height > following:
            raise ValueError('Строка таблицы не помещается в рабочую область; нужна ручная проверка')
        if used+height > available:
            if not chunks[-1]:
                # The first header has already been rendered with a data row;
                # a safety reserve cannot silently move it past nearby prose.
                raise ValueError('Недостаточно места для первой части таблицы; нужна проверка переноса')
            chunks.append([]); used,available=0.,following
        chunks[-1].extend(group); used += height
    return chunks


def split_tables(root: Any, boxes: dict[tuple[int,int],list[RowBox]], reserve: float,
                 *, only_table: Any = None) -> int:
    original = _text_nodes(root)
    generated: set[Any] = set()
    count = 0
    for t_index,flow in enumerate(flows(root)):
        if only_table is not None and flow.table is not only_table:
            continue
        table,caption = flow.table,flow.caption
        rows = table.findall(W+'tr')
        locations = [boxes.get((t_index,i),[]) for i in range(len(rows))]
        if any(not values for values in locations) or any(len(values)!=1 for values in locations[flow.headers:]):
            raise ValueError('Неоднозначное положение строки таблицы; документ не публикуется')
        first_headers = [values[0] for values in locations[:flow.headers]]
        start = min(b.top for b in first_headers)
        header_height = max(b.bottom for b in first_headers)-start
        heights = [(values[0].bottom-values[0].top)*1.035+1 for values in locations[flow.headers:]]
        following = flow.bottom-flow.top-header_height-23-reserve
        first = flow.bottom-start-header_height-reserve
        last_note = len(rows[-1].findall(W+'tc'))==1 and _text(rows[-1]).lower().startswith('примечан')
        # If a table already fits with comfortable reserve, its XML stays intact.
        if sum(heights) <= first:
            continue
        chunks = pack_rows(heights,first,following,keep_last=last_note)
        parent = table.getparent(); position = list(parent).index(table)
        headers = rows[:flow.headers]
        for row in rows[flow.headers:]:
            table.remove(row)
        data = rows[flow.headers:]
        for chunk_index,chunk in enumerate(chunks):
            if chunk_index == 0:
                target = table
            else:
                new_caption = copy.deepcopy(caption)
                for key in list(new_caption.attrib):
                    if key in {'{http://schemas.microsoft.com/office/word/2010/wordml}paraId',
                               '{http://schemas.microsoft.com/office/word/2010/wordml}textId'}:
                        del new_caption.attrib[key]
                for child in list(new_caption):
                    if child.tag != W+'pPr':
                        new_caption.remove(child)
                pr = _node(new_caption,'pPr')
                for tag in ('numPr','sectPr'):
                    node = pr.find(W+tag)
                    if node is not None:
                        pr.remove(node)
                _paragraph(new_caption,12,keep=True)
                _set(pr,'pageBreakBefore',val='1')
                text = ET.SubElement(ET.SubElement(new_caption,W+'r'),W+'t')
                text.text = 'Продолжение таблицы '+flow.number
                _paragraph(new_caption,12,keep=True)
                _set(pr,'pageBreakBefore',val='1')
                generated.add(text)
                target = ET.Element(W+'tbl',nsmap=table.nsmap)
                for child in table:
                    if child.tag in {W+'tblPr',W+'tblGrid'}:
                        target.append(copy.deepcopy(child))
                for row in headers:
                    clone = copy.deepcopy(row); target.append(clone)
                    for node in clone.iter():
                        for key in list(node.attrib):
                            if key in {'{http://schemas.microsoft.com/office/word/2010/wordml}paraId',
                                       '{http://schemas.microsoft.com/office/word/2010/wordml}textId'}:
                                del node.attrib[key]
                    generated.update(_text_nodes(clone))
                parent.insert(position+1,new_caption); parent.insert(position+2,target)
                position += 2
                count += 1
            for index in chunk:
                target.append(data[index])
    _check_text(root,original,set(),generated)
    return count


def verify_chunks(root: Any, boxes: dict[tuple[int,int],list[RowBox]]) -> bool:
    for t_index,flow in enumerate(flows(root)):
        rows = flow.table.findall(W+'tr')
        locations = [boxes.get((t_index,i),[]) for i in range(len(rows))]
        if any(len(values)!=1 for values in locations):
            return False
        values = [v[0] for v in locations]
        if len({v.page for v in values})!=1 or max(v.bottom for v in values)>flow.bottom-2.5:
            return False
    return True


def paginate_tables(path: Path, convert: Converter) -> tuple[int, int, int]:
    """Bounded render/measure/split/verify stage, inside the document container."""
    root = _read(path)
    merged = merge_manual_parts(root)
    supported = flows(root)
    body = root.find(W+'body')
    captioned = sum(1 for table in body.findall(W+'tbl')
                    if _caption_before(body,table) is not None
                    or (table.findall(W+'tr') and TABLE.match(_text(table.findall(W+'tr')[0]))))
    skipped = captioned-len(supported)
    if not supported:
        return 0,0,skipped
    work = path.parent.parent/'table-layout'; work.mkdir(exist_ok=True)
    analysis = work/'measure.docx'; probe(path,analysis,root)
    boxes = measure(convert(analysis,work/'measure-pdf','pdf:writer_pdf_Export'))
    total = 0
    # Work in document order. Every split changes the positions of later
    # tables. Re-measure before planning the next one, rather than repeatedly
    # splitting already fragmented candidates using stale page offsets.
    for index,flow in enumerate(supported):
        count = split_tables(root,boxes,10,only_table=flow.table)
        if not count:
            continue
        total += count
        check = work/f'check-{index}.docx'; probe(path,check,root)
        boxes = measure(convert(check,work/f'check-pdf-{index}','pdf:writer_pdf_Export'))
    if not verify_chunks(root,boxes):
        raise ValueError('Не удалось стабилизировать переносы таблиц; документ не публикуется')
    result = work/'result.docx'; _save(path,result,root)
    path.write_bytes(result.read_bytes())
    return merged,total,skipped
