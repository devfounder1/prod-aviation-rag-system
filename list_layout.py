"""Measured paragraph-style wrapping for explicit body lists, without renumbering.

ГОСТ Р 2.105-2019 6.7.2/6.7.8 allow per-level layout choices. The
chosen recipe uses a positive first-line indent, not Word's hanging indent:
wrapped lines return to the level's text boundary as in the supplied example.
Numbered notes are separate (6.12); text, labels and counters remain intact.
"""
from __future__ import annotations

from dataclasses import dataclass
import copy
import re
from typing import Any

from lxml import etree as ET  # type: ignore[import-untyped]

from document_elements import NS, W, _node, _set, _text


@dataclass(frozen=True)
class ListReport:
    items: int
    notes: int
    soft_breaks: int
    warnings: tuple[str, ...]


def _chain(paragraph: Any, styles: Any, *, protect_headings: bool = True) -> list[Any]:
    result = []
    own = paragraph.find(W + 'pPr')
    if own is not None:
        result.append(own)
    style = own.find(W + 'pStyle') if own is not None else None
    key = style.get(W + 'val') if style is not None else None
    if key is None and styles is not None:
        default = styles.find("w:style[@w:type='paragraph'][@w:default='1']", NS)
        key = default.get(W + 'styleId') if default is not None else None
    seen: set[str] = set()
    while key and key not in seen and styles is not None:
        seen.add(key)
        found = next((s for s in styles.findall(W + 'style') if s.get(W + 'styleId') == key), None)
        if found is None:
            break
        name = found.find(W + 'name')
        role = name.get(W + 'val', '').lower().replace(' ', '') if name is not None else ''
        if protect_headings and role.startswith(('heading', 'заголовок', 'toc', 'содержание')):
            return []
        properties = found.find(W + 'pPr')
        if properties is not None:
            result.append(properties)
        base = found.find(W + 'basedOn')
        key = base.get(W + 'val') if base is not None else None
    if protect_headings and any(node.get(W+'val') != '9' for p in result
           for node in p.findall(W+'outlineLvl')):
        return []
    return result


def _level(chain: list[Any], numbering: Any) -> tuple[str, int, Any] | None:
    def prop(tag: str) -> str | None:
        for ppr in chain:
            node = ppr.find('w:numPr/w:' + tag, NS)
            if node is not None:
                return str(node.get(W + 'val', ''))
        return None
    identifier, index = prop('numId'), prop('ilvl') or '0'
    if not identifier or identifier == '0' or not re.fullmatch('[0-8]', index) or numbering is None:
        return None
    num = next((n for n in numbering.findall(W + 'num') if n.get(W + 'numId') == identifier), None)
    if num is None:
        return None
    override = num.find("w:lvlOverride[@w:ilvl='" + index + "']/w:lvl", NS)
    if override is not None:
        return identifier, int(index), override
    ref = num.find(W + 'abstractNumId')
    if ref is None:
        return None
    abstract = next((a for a in numbering.findall(W + 'abstractNum')
                     if a.get(W + 'abstractNumId') == ref.get(W + 'val')), None)
    if abstract is None or abstract.find(W + 'numStyleLink') is not None:
        return None
    level = abstract.find("w:lvl[@w:ilvl='" + index + "']", NS)
    return (identifier, int(index), level) if level is not None else None


def _soft_breaks(paragraph: Any) -> int:
    """Remove only whitespace-adjacent run breaks, never page/column/clear breaks.

    No w:t node is changed. Hard multi-line constructs without whitespace stay
    intact for review rather than joining words or fabricating separators.
    """
    tokens = paragraph.xpath('./w:r/w:t | ./w:r/w:br | ./w:r/w:cr | ./w:r/w:tab', namespaces=NS)
    count = 0
    for i, node in enumerate(tokens):
        if node.tag not in {W + 'br', W + 'cr'}:
            continue
        if node.get(W + 'type', 'textWrapping') != 'textWrapping' or node.get(W + 'clear') is not None:
            continue
        if i == 0 or i + 1 == len(tokens) or tokens[i-1].tag != W+'t' or tokens[i+1].tag != W+'t':
            continue
        left, right = tokens[i-1].text or '', tokens[i+1].text or ''
        if not left or not right or not (left[-1].isspace() or right[0].isspace()):
            continue
        node.getparent().remove(node)
        count += 1
    return count


def normalize_lists(document: Any, styles: Any, numbering: Any, indent_mm: float) -> ListReport:
    body = document.find(W + 'body')
    if body is None:
        return ListReport(0, 0, 0, ())
    items = notes = breaks = 0
    warnings: list[str] = []
    # Group actual adjacent list paragraphs, including nested levels, never table
    # content or section boundaries. A blank paragraph ends a group deliberately.
    groups: list[list[tuple[Any, list[Any], tuple[str, int, Any]]]] = []
    previous_id: str | None = None
    note_groups: set[int] = set()
    previous_text = ''
    introductions: dict[int, str] = {}
    for paragraph in body:
        chain = _chain(paragraph, styles) if paragraph.tag == W+'p' else []
        level = _level(chain, numbering)
        plain = _text(paragraph)
        if (not chain or level is None or not plain
                or paragraph.xpath('.//w:drawing | .//w:pict | .//w:object | .//w:fldChar | .//w:instrText | .//w:del | .//w:ins', namespaces=NS)
                or any(p.find(W+'framePr') is not None or p.find(W+'sectPr') is not None
                       or any(n.get(W+'val', '1') not in {'0', 'false', 'off'} for n in p.findall(W+'bidi')) for p in chain)):
            previous_id = None
            previous_text = plain
            continue
        if previous_id != level[0]:
            groups.append([])
            introductions[len(groups)-1] = previous_text
            if re.fullmatch(r'Примечания\s*:?\s*', previous_text, re.I):
                note_groups.add(len(groups)-1)
        groups[-1].append((paragraph, chain, level))
        previous_id = level[0]
        previous_text = plain
    step = round(indent_mm * 1440 / 25.4)
    eligible = []
    for group_index, group in enumerate(groups):
        is_note = group_index in note_groups
        if len(group) < 2:
            warnings.append('Одиночный или разорванный список оставлен для проверки: ' + _text(group[0][0])[:65])
            continue
        # Never reinterpret hierarchical section/requirement numbers as lists.
        valid = True
        for _, _, (_, index, lvl) in group:
            fmt, label = lvl.find(W+'numFmt'), lvl.find(W+'lvlText')
            kind = fmt.get(W+'val', '') if fmt is not None else ''
            text = label.get(W+'val', '') if label is not None else ''
            if not (kind == 'bullet' or (kind in {'decimal', 'lowerLetter', 'upperLetter', 'lowerRoman', 'upperRoman', 'russianLower', 'russianUpper'}
                    and text in ({f'%{index+1})', f'%{index+1}.'} if is_note else {f'%{index+1})'}))):
                valid = False
        if any(p.xpath('./w:r/w:tab', namespaces=NS) for p, _, _ in group):
            valid = False
            warnings.append('Список с табуляциями внутри текста оставлен для ручной проверки.')
        if not valid:
            # No guessed conversion of referenced counters or legacy definitions.
            continue
        eligible.append((group_index, group, is_note))
    planned = {p for _, group, _ in eligible for p, _, _ in group}
    blocked: set[str] = set()
    for paragraph in document.findall('.//w:p', NS):
        level = _level(_chain(paragraph, styles, protect_headings=False), numbering)
        if level is not None and paragraph not in planned:
            blocked.add(level[0])
    used: dict[str, set[int]] = {}
    seen_numbered: set[str] = set()
    for group_index, group, is_note in eligible:
        identifier = group[0][2][0]
        if identifier in blocked:
            warnings.append('Счётчик списка используется также в защищённом/неоднозначном блоке; отступы оставлены для проверки.')
            continue
        used.setdefault(identifier, set()).update(level[1] for _, _, level in group)
        for paragraph, chain, (_, index, lvl) in group:
            ppr = _node(paragraph, 'pPr')
            indent = _node(ppr, 'ind')
            for attr in ('hanging', 'hangingChars', 'firstLineChars', 'leftChars', 'rightChars', 'startChars', 'endChars'):
                indent.attrib.pop(W+attr, None)
            left = index * step
            _set(ppr, 'ind', left=str(left), start=str(left), firstLine=str(step), right='0', end='0')
            # Clear inherited stop positions before installing one explicit stop.
            positions = {tab.get(W+'pos') for properties in [*chain, lvl.find(W+'pPr')]
                         if properties is not None for tab in properties.findall('w:tabs/w:tab', NS)}
            tabs = _node(ppr, 'tabs')
            tabs[:] = []
            for position in sorted(p for p in positions if p and p.lstrip('-').isdigit()):
                tab = ET.SubElement(tabs, W+'tab')
                tab.set(W+'val', 'clear'); tab.set(W+'pos', position)
            # Generous label slot also fits two-digit and Roman labels. This is
            # a project choice, not a numerical requirement inferred from pixels.
            tab = ET.SubElement(tabs, W+'tab')
            tab.set(W+'val', 'num'); tab.set(W+'pos', str(left + step + 360))
            _set(ppr, 'wordWrap', val='1')
            _set(ppr, 'snapToGrid', val='0')
            _set(ppr, 'adjustRightInd', val='0')
            _set(ppr, 'keepNext', val='0'); _set(ppr, 'keepLines', val='0')
            _set(ppr, 'widowControl', val='1')
            if not is_note:
                _node(ppr, 'spacing').attrib.clear()
                _set(ppr, 'spacing', before='0', after='0', line='360', lineRule='auto')
            breaks += _soft_breaks(paragraph)
            if paragraph.xpath('./w:r/w:br | ./w:r/w:cr', namespaces=NS):
                warnings.append('Сохранён неоднозначный ручной перенос в списке: ' + _text(paragraph)[:65])
            if is_note:
                notes += 1
            else:
                items += 1
        if not is_note:
            initial = group[0][2][2].find(W+'numFmt')
            if initial is not None and initial.get(W+'val') != 'bullet':
                if identifier in seen_numbered:
                    warnings.append('Проверить перезапуск нумерации отдельного списка: исходный счётчик используется повторно.')
                seen_numbered.add(identifier)
            uppercase = next((_text(p)[:65] for p, _, _ in group
                              if _text(p).lstrip('«“\"(')[:1].isupper()), '')
            if uppercase:
                warnings.append('Проверить прописную букву в начале пункта (названия и сокращения не менялись): ' + uppercase)
            if not introductions[group_index].endswith(':'):
                warnings.append('Проверить общую вводную формулировку и двоеточие перед списком: ' + _text(group[0][0])[:65])
            for paragraph, _, (_, index, lvl) in group:
                fmt = lvl.find(W+'numFmt')
                if fmt is not None and fmt.get(W+'val') == 'bullet':
                    label = lvl.find(W+'lvlText')
                    if label is not None and label.get(W+'val') not in {'-', '\uf02d'}:
                        warnings.append('Маркер списка сохранён; для символа, отличного от дефиса, нужна норма организации.')
            # Punctuation/case may encode abbreviations, multi-sentence items or
            # names. Audit endings at each nesting level, never rewrite words.
            for i, (paragraph, _, (_, index, _)) in enumerate(group):
                following = next((other[2][1] for other in group[i+1:] if other[2][1] <= index), -1)
                required = ':' if i+1 < len(group) and group[i+1][2][1] > index else (';' if following == index else '.')
                if not _text(paragraph).endswith(required):
                    warnings.append(f'Проверить знак в конце пункта (ожидается «{required}», текст сохранён): ' + _text(paragraph)[-70:])
    _numbering_layout(numbering, used, step)
    return ListReport(items, notes, breaks, tuple(dict.fromkeys(warnings)))


def _numbering_layout(numbering: Any, used: dict[str, set[int]], step: int) -> None:
    """Clone layout definitions; retain IDs, counters, restarts and original defs.

    LibreOffice can prioritize a numbering-level hanging indent over paragraph
    firstLine. Update both geometry layers. Only fully classified counters enter
    this operation; shared unknown/table/heading users prevent modification.
    """
    if numbering is None:
        return
    existing = {a.get(W+'abstractNumId'): a for a in numbering.findall(W+'abstractNum')}
    identifiers = [int(key) for key in existing if key is not None and key.isdigit()]
    next_id = max(identifiers, default=-1) + 1
    for num in numbering.findall(W+'num'):
        identifier = num.get(W+'numId')
        if identifier not in used:
            continue
        ref = num.find(W+'abstractNumId')
        if ref is None or ref.get(W+'val') not in existing:
            continue
        clone = copy.deepcopy(existing[ref.get(W+'val')])
        clone.set(W+'abstractNumId', str(next_id))
        # Unique layout definition keeps all counter settings and font runs.
        ref.set(W+'val', str(next_id)); next_id += 1
        for index in used[identifier]:
            level = num.find("w:lvlOverride[@w:ilvl='"+str(index)+"']/w:lvl", NS)
            if level is None:
                level = clone.find("w:lvl[@w:ilvl='"+str(index)+"']", NS)
            if level is None:
                continue
            ppr = _node(level,'pPr')
            indent = _node(ppr,'ind'); indent.attrib.clear()
            _set(ppr,'ind', left=str(index*step), start=str(index*step), firstLine=str(step))
            tabs = _node(ppr,'tabs'); tabs[:] = []
            tab = ET.SubElement(tabs,W+'tab'); tab.set(W+'val','num'); tab.set(W+'pos',str((index+1)*step+360))
            # Original right alignment makes marker position width-dependent.
            # Preserve the characters/counters and align their leading edge.
            align = level.find(W+'lvlJc')
            if align is None:
                align = ET.Element(W+'lvlJc')
                position = list(level).index(ppr)
                level.insert(position,align)
            align.set(W+'val','left')
        numbering.insert(list(numbering).index(numbering.find(W+'num')),clone)
