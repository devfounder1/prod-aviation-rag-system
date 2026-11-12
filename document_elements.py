"""Conservative layout of captioned technical tables and existing pictures.

Operate only on body elements with an unambiguous caption. Preserve cell text,
merges, field instructions, relationships, picture crops and binary payloads.
Unsupported geometry stays intact and is reported for review.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any

from lxml import etree as ET  # type: ignore[import-untyped]

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
WP = '{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
NS = {'w': W[1:-1], 'wp': WP[1:-1], 'a': A[1:-1],
      'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture'}
NUMBER = r'[А-ЯA-Zа-яa-z]?\.?\d+(?:\.\d+)*'
TABLE = re.compile(r'^(?:Таблица|Продолжение\s+таблицы)\s+(' + NUMBER + r')\b', re.I)
FIGURE = re.compile(r'^Рисунок\s+(' + NUMBER + r')\b', re.I)
PROPERTY_ORDER = {
    'pPr': 'pStyle keepNext keepLines pageBreakBefore framePr widowControl numPr suppressLineNumbers pBdr shd tabs suppressAutoHyphens kinsoku wordWrap overflowPunct topLinePunct autoSpaceDE autoSpaceDN bidi adjustRightInd snapToGrid spacing ind contextualSpacing mirrorIndents suppressOverlap jc textDirection textAlignment textboxTightWrap outlineLvl divId cnfStyle rPr sectPr pPrChange',
    'rPr': 'rStyle rFonts b bCs i iCs caps smallCaps strike dStrike outline shadow emboss imprint noProof snapToGrid vanish webHidden color spacing w kern position sz szCs highlight u effect bdr shd fitText vertAlign rtl cs em lang eastAsianLayout specVanish oMath rPrChange',
    'tblPr': 'tblStyle tblpPr tblOverlap bidiVisual tblStyleRowBandSize tblStyleColBandSize tblW jc tblCellSpacing tblInd tblBorders shd tblLayout tblCellMar tblLook tblCaption tblDescription tblPrChange',
    'trPr': 'cnfStyle divId gridBefore gridAfter wBefore wAfter cantSplit trHeight tblHeader tblCellSpacing jc hidden ins del trPrChange',
    'tcPr': 'cnfStyle tcW gridSpan hMerge vMerge tcBorders shd noWrap tcMar textDirection tcFitText vAlign hideMark headers cellIns cellDel cellMerge tcPrChange',
}


@dataclass(frozen=True)
class ElementReport:
    tables: int
    figures: int
    warnings: tuple[str, ...]


def _node(parent: Any, tag: str) -> Any:
    child = parent.find(W + tag)
    if child is None:
        child = ET.SubElement(parent, W + tag)
        if tag in {'pPr', 'rPr', 'trPr', 'tcPr', 'tblPr'}:
            parent.remove(child); parent.insert(0, child)
        order = PROPERTY_ORDER.get(ET.QName(parent).localname)
        if order:
            rank = {W + name: n for n, name in enumerate(order.split())}
            parent[:] = sorted(parent, key=lambda item: rank.get(item.tag, len(rank)))
    return child


def _set(parent: Any, tag: str, **values: str) -> None:
    child = _node(parent, tag)
    for key, value in values.items():
        child.set(W + key, value)


def _text(node: Any) -> str:
    return ''.join(node.xpath('.//w:t/text()', namespaces=NS)).strip()


def _integer(node: Any, attribute: str, default: int = 0) -> int:
    try:
        return int(node.get(W + attribute, str(default))) if node is not None else default
    except (TypeError, ValueError):
        return default


def _section_bounds(body: Any, block: Any) -> tuple[int, int]:
    # A sectPr describes the preceding section, so find the next section end.
    children = list(body)
    for child in children[children.index(block):]:
        section = child if child.tag == W + 'sectPr' else child.find('w:pPr/w:sectPr', NS)
        if section is not None:
            size, margins = section.find(W + 'pgSz'), section.find(W + 'pgMar')
            width = _integer(size, 'w', 11906) - _integer(margins, 'left', 1440) - _integer(margins, 'right', 1440) - _integer(margins, 'gutter')
            height = _integer(size, 'h', 16838) - _integer(margins, 'top', 1440) - _integer(margins, 'bottom', 1440)
            return max(1440, width), max(1440, height)
    return 9026, 13958


def _paragraph(paragraph: Any, size: int, *, keep: bool, center: bool = False) -> None:
    ppr = _node(paragraph, 'pPr')
    _set(ppr, 'keepNext', val='1' if keep else '0')
    _set(ppr, 'keepLines', val='1')
    _set(ppr, 'pageBreakBefore', val='0')
    _set(ppr, 'wordWrap', val='1')
    _set(ppr, 'spacing', before='0', after='60', line='240', lineRule='auto')
    indent = _node(ppr, 'ind')
    if ppr.find(W + 'numPr') is not None:
        indent.attrib.pop(W + 'firstLine', None)
        _set(ppr, 'ind', hanging='300', left='360', start='360', right='0', end='0')
        tabs = ppr.find(W + 'tabs')
        if tabs is not None:
            for tab in tabs.findall(W + 'tab'):
                if tab.get(W + 'val') in {'num', 'left'}:
                    tab.set(W + 'pos', '360')
    else:
        indent.attrib.pop(W + 'hanging', None)
        _set(ppr, 'ind', firstLine='0', left='0', start='0', right='0', end='0')
    _set(ppr, 'jc', val='center' if center else 'left')
    for run in paragraph.xpath('./w:r[w:t] | ./w:hyperlink/w:r[w:t]', namespaces=NS):
        rpr = _node(run, 'rPr')
        # Do not enlarge explicitly small superscripts or subscripts.
        if rpr.find(W + 'vertAlign') is None:
            _set(rpr, 'sz', val=str(size * 2)); _set(rpr, 'szCs', val=str(size * 2))


def _header_rows(rows: list[Any]) -> int:
    count = 0
    for row in rows:
        header = row.find('w:trPr/w:tblHeader', NS)
        if header is None or header.get(W + 'val', '1') in {'0', 'false', 'off'}:
            break
        count += 1
    if not count:
        labels = ('наименование', 'номер', 'обозначение', 'количество', 'значение',
                  'примечание', 'погрешность', 'отклонени', 'мдпи')
        cells = rows[0].findall(W + 'tc')
        if sum(any(key in _text(cell).lower() for key in labels) for cell in cells) < 2:
            return 0
        count = 1
    # A vertical merge must finish inside the repeated header group. Extend
    # only across actual continuation cells, never arbitrary following data.
    while count < min(4, len(rows)):
        previous = rows[count - 1].findall(W + 'tc')
        current = rows[count].findall(W + 'tc')
        if (any(c.find('w:tcPr/w:vMerge', NS) is not None for c in previous)
                and any(c.find('w:tcPr/w:vMerge', NS) is not None
                        and c.find('w:tcPr/w:vMerge', NS).get(W + 'val', 'continue') == 'continue'
                        for c in current)):
            count += 1
        else:
            break
    if count < len(rows) and count == 4:
        if any(c.find('w:tcPr/w:vMerge', NS) is not None
               and c.find('w:tcPr/w:vMerge', NS).get(W + 'val', 'continue') == 'continue'
               for c in rows[count].findall(W + 'tc')):
            return 0
    return count if count < len(rows) else 0


def _grid(table: Any, width: int) -> list[int] | None:
    columns = table.findall('w:tblGrid/w:gridCol', NS)
    widths = [_integer(column, 'w') for column in columns]
    if not widths or min(widths) < 1:
        return None
    for row in table.findall(W + 'tr'):
        before = _integer(row.find('w:trPr/w:gridBefore', NS), 'val')
        after = _integer(row.find('w:trPr/w:gridAfter', NS), 'val')
        spans = [_integer(cell.find('w:tcPr/w:gridSpan', NS), 'val', 1) for cell in row.findall(W + 'tc')]
        if before < 0 or after < 0 or min(spans, default=0) < 1 or before + sum(spans) + after != len(widths):
            return None
    if sum(widths) > width:
        scale = width / sum(widths)
        widths = [max(1, int(value * scale)) for value in widths]
        widths[-1] += width - sum(widths)
        if min(widths) < 240:
            return None
        for column, value in zip(columns, widths):
            column.set(W + 'w', str(value))
    return widths


def _table(table: Any, caption: Any, width: int, height: int, size: int, header_size: int) -> str | None:
    if table.xpath('.//w:tbl | .//w:drawing | .//w:pict | .//w:object | ./w:tblPr/w:tblpPr', namespaces=NS):
        return 'Сложная или плавающая таблица сохранена без изменения геометрии.'
    rows = table.findall(W + 'tr')
    if not rows:
        return 'Пустая таблица оставлена без изменений.'
    # Validate the complete grid before making any changes.
    widths = _grid(table, width)
    if widths is None:
        return 'Неоднозначная сетка таблицы: оформление оставлено для ручной проверки.'
    headers = _header_rows(rows)
    tpr = _node(table, 'tblPr')
    _set(tpr, 'tblW', w=str(sum(widths)), type='dxa')
    _set(tpr, 'tblInd', w='0', type='dxa')
    _set(tpr, 'jc', val='center')
    _set(tpr, 'tblLayout', type='fixed')
    margins = _node(tpr, 'tblCellMar')
    for side in ('top', 'bottom'):
        _set(margins, side, w='40', type='dxa')
    for side in ('left', 'right'):
        _set(margins, side, w='70', type='dxa')
    row_heights: list[int] = []
    for index, row in enumerate(rows):
        rpr = _node(row, 'trPr')
        _set(rpr, 'tblHeader', val='1' if index < headers else '0')
        row_height = rpr.find(W + 'trHeight')
        if row_height is not None and row_height.get(W + 'hRule') == 'exact':
            row_height.set(W + 'hRule', 'atLeast')
        column = _integer(rpr.find(W + 'gridBefore'), 'val')
        estimated_height = 0
        font_size = header_size if index < headers else size
        for cell in row.findall(W + 'tc'):
            cpr = _node(cell, 'tcPr')
            span = _integer(cpr.find(W + 'gridSpan'), 'val', 1)
            cell_width = sum(widths[column:column + span]); column += span
            _set(cpr, 'tcW', w=str(cell_width), type='dxa')
            _set(cpr, 'noWrap', val='0')
            _set(cpr, 'vAlign', val='center')
            cell_margins = _node(cpr, 'tcMar')
            padding = '40' if index < headers else '70'
            for side, value in (('top', '40'), ('bottom', '40'), ('left', padding), ('right', padding)):
                _set(cell_margins, side, w=value, type='dxa')
            lines = 0
            paragraphs = cell.findall(W + 'p')
            for p_index, paragraph in enumerate(paragraphs):
                _paragraph(paragraph, font_size, keep=index < headers or p_index < len(paragraphs) - 1,
                           center=index < headers)
                chars_per_line = max(1, (cell_width - 140) / (font_size * 10))
                lines += sum(max(1, math.ceil(len(line) / chars_per_line))
                             for line in re.split(r'[\r\n]', _text(paragraph)))
                if index == 0 and headers:
                    for run in paragraph.xpath('.//w:r[w:t]', namespaces=NS):
                        _set(_node(run, 'rPr'), 'b', val='1')
            estimated_height = max(estimated_height, lines * font_size * 24 + 80)
        # Long prose rows must remain splittable, otherwise the table can be
        # pushed beyond a page or lose content in particular Word renderers.
        _set(rpr, 'cantSplit', val='1' if estimated_height < height * 0.45 else '0')
        row_heights.append(estimated_height)
        if index >= headers and estimated_height >= height * 0.45:
            for paragraph in row.xpath('./w:tc/w:p', namespaces=NS):
                _set(_node(paragraph, 'pPr'), 'keepLines', val='0')
                _set(_node(paragraph, 'pPr'), 'keepNext', val='0')
    # Avoid an otherwise empty page containing only the repeated header and a
    # short final note; bind the note to the preceding record when both fit.
    if (len(rows) > headers + 1 and len(rows[-1].findall(W + 'tc')) == 1
            and _text(rows[-1]).lower().startswith('примечан')
            and sum(row_heights[-2:]) < height * 0.6):
        for paragraph in rows[-2].xpath('./w:tc/w:p', namespaces=NS):
            _set(_node(paragraph, 'pPr'), 'keepNext', val='1')
    _paragraph(caption, size, keep=True)
    if _text(caption).lower().startswith('продолжение'):
        _set(_node(caption, 'pPr'), 'pageBreakBefore', val='1')
    return None if headers else 'Головка таблицы не определена: строки данных не назначены заголовком.'


def _fit_picture(picture: Any, max_width: int, max_height: int) -> bool:
    graphic = picture.find(A + 'graphic')
    extent = picture.find(WP + 'extent')
    if (graphic is None or extent is None or not graphic.xpath('./a:graphicData/pic:pic', namespaces=NS)):
        return False
    try:
        width, height = int(extent.get('cx')), int(extent.get('cy'))
    except (TypeError, ValueError):
        return False
    if width <= 0 or height <= 0:
        return False
    transform = graphic.find('.//{http://schemas.openxmlformats.org/drawingml/2006/picture}spPr/' + A + 'xfrm')
    inner = transform.find(A + 'ext') if transform is not None else None
    if inner is None or transform.get('rot', '0') != '0':
        return False
    scale = min(1.0, max_width * 635 / width, max_height * 635 / height)
    new_width, new_height = round(width * scale), round(height * scale)
    extent.set('cx', str(new_width)); extent.set('cy', str(new_height))
    inner.set('cx', str(new_width)); inner.set('cy', str(new_height))
    # A simple picture can safely join document flow. Its editable image and
    # crop are retained; floating groups/textboxes/diagrams are never flattened.
    if picture.tag == WP + 'anchor':
        picture.tag = WP + 'inline'
        picture.attrib.clear()
        allowed = {WP + name for name in ('extent', 'effectExtent', 'docPr', 'cNvGraphicFramePr')} | {A + 'graphic'}
        for child in list(picture):
            if child.tag not in allowed:
                picture.remove(child)
    for attr in ('distT', 'distB', 'distL', 'distR'):
        picture.set(attr, '0')
    return True


def _figures(body: Any, size: int) -> tuple[int, list[str]]:
    count = 0
    warnings: list[str] = []
    blocks = list(body)
    for index, paragraph in enumerate(blocks):
        if paragraph.tag != W + 'p' or not paragraph.xpath('.//w:drawing | .//w:pict | .//w:object', namespaces=NS):
            continue
        following: list[Any] = []
        caption = None
        for block in blocks[index + 1:index + 10]:
            if block.tag != W + 'p' or block.xpath('.//w:drawing | .//w:pict | .//w:object', namespaces=NS):
                break
            following.append(block)
            if FIGURE.match(_text(block)):
                caption = block; break
            if block.find('w:pPr/w:sectPr', NS) is not None:
                break
        if caption is None:
            warnings.append('Изображение без однозначной подписи сохранено на исходном месте.')
            continue
        pictures = paragraph.xpath('./w:r/w:drawing/wp:anchor | ./w:r/w:drawing/wp:inline', namespaces=NS)
        if len(pictures) != 1 or len(paragraph.xpath('.//w:drawing | .//w:pict | .//w:object', namespaces=NS)) != 1:
            warnings.append('Сложный рисунок ' + _text(caption)[:60] + ' оставлен без изменения геометрии.')
            continue
        picture = pictures[0]
        run = picture.getparent().getparent()
        if any(child.tag not in {W + 'rPr', W + 'drawing'} for child in run):
            warnings.append('Смешанное содержимое рисунка оставлено для ручной проверки.'); continue
        width, height = _section_bounds(body, paragraph)
        # Reserve room for the existing heading, notes and caption. This is a
        # conservative layout budget, not a compliance measurement in pixels.
        reserve = 360 + sum(max(1, math.ceil(len(_text(p)) / max(1, width / (size * 10))))
                            * size * 24 + 60 for p in following)
        if _text(paragraph):
            reserve += 1400
        available_height = height - reserve
        if available_height < height * 0.4 or not _fit_picture(picture, width, available_height):
            warnings.append('Рисунок не удалось безопасно вписать: ' + _text(caption)[:60]); continue
        graphic_paragraph = paragraph
        if _text(paragraph):
            # Legacy imports often anchor a figure to its appendix heading.
            # Move only the drawing-only run into a following centered paragraph.
            paragraph.remove(run)
            graphic_paragraph = ET.Element(W + 'p')
            graphic_paragraph.append(run)
            body.insert(list(body).index(paragraph) + 1, graphic_paragraph)
        _paragraph(graphic_paragraph, size, keep=True, center=True)
        for block in following:
            _paragraph(block, size, keep=block is not caption, center=block is caption)
        count += 1
    return count, warnings


def _references(body: Any) -> list[str]:
    captions: dict[tuple[str, str], int] = {}
    prose: list[str] = []
    for paragraph in body.findall(W + 'p'):
        text = _text(paragraph)
        table, figure = TABLE.match(text), FIGURE.match(text)
        if table or figure:
            match = table if table else figure
            assert match is not None
            if text.lower().startswith('продолжение'):
                continue
            key = ('таблица' if table else 'рисунок', match.group(1).upper())
            captions[key] = captions.get(key, 0) + 1
        else:
            prose.append(text)
    text = '\n'.join(prose)
    warnings = []
    for (kind, number), count in captions.items():
        if count > 1:
            warnings.append(f'Повторяется обозначение: {kind} {number}. Нумерация сохранена.')
        expression = (r'таблиц(?:а|ы|е|у|ей|ах|ам|ами)?' if kind == 'таблица'
                      else r'рисун(?:ок|ка|ке|ку|ком|ки|ках|ков|кам|ками)')
        mentions: set[str] = set()
        for match in re.finditer(r'\b' + expression + r'\s+(' + NUMBER +
                                 r'(?:\s*(?:,|и|–|—|-|до)\s*' + NUMBER + r')*)(?!\w|\.\d)', text, re.I):
            values = re.findall(NUMBER, match.group(1))
            mentions.update(value.upper() for value in values)
            if len(values) == 2 and all(value.isdecimal() for value in values) and re.search(r'[–—-]|\bдо\b', match.group(1)):
                start, end = (int(value) for value in values)
                if 0 < end - start <= 100:
                    mentions.update(str(value) for value in range(start, end + 1))
        if number not in mentions:
            warnings.append(f'Проверьте ссылку в тексте: {kind} {number}. Автоматически не добавлялась.')
    return warnings


def normalize_elements(document: Any, table_pt: int, table_header_pt: int = 11) -> ElementReport:
    body = document.find(W + 'body')
    if body is None:
        return ElementReport(0, 0, ())
    tables = 0
    warnings: list[str] = []
    blocks = list(body)
    for index, table in enumerate(blocks):
        if table.tag != W + 'tbl':
            continue
        previous = index - 1
        while previous >= 0 and blocks[previous].tag == W + 'p' and not _text(blocks[previous]):
            previous -= 1
        if previous < 0 or blocks[previous].tag != W + 'p' or not TABLE.match(_text(blocks[previous])):
            continue
        caption = blocks[previous]
        width, height = _section_bounds(body, table)
        warning = _table(table, caption, width, height, table_pt, table_header_pt)
        if warning:
            warnings.append(_text(caption)[:60] + ': ' + warning)
        if warning is None or warning.startswith('Головка'):
            tables += 1
    figures, figure_warnings = _figures(body, table_pt)
    return ElementReport(tables, figures, tuple(warnings + figure_warnings + _references(body)))
