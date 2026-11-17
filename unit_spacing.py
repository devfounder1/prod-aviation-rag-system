"""Bind explicit numeric quantities to known unit tokens (ГОСТ 6.16.6).

Only replace existing ASCII spaces with NBSP, including across styled runs.
No number/unit spelling, punctuation, run, field, object or paragraph is rewritten.
Unsupported notation and manual breaks remain review items, not guessed values.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from document_elements import NS, W

NBSP = '\u00a0'
# Explicit token vocabulary, not a full SI parser. Longer compound units win.
UNITS = (
    'мм рт. ст.', 'кг/м³', 'кг/м3', 'м/с²', 'м/с2', 'м/с', 'км/ч', 'Н·м',
    '° C', '° С', '°C', '°С', '°F', '° F', 'мкм', 'мм', 'см', 'дм', 'км',
    'мкг', 'мг', 'кг', 'кН', 'мкА', 'мА', 'кА', 'мкВ', 'мВ', 'кВ',
    'мкВт', 'мВт', 'кВт', 'МВт', 'Вт', 'кОм', 'МОм', 'Ом', 'ГГц', 'МГц', 'кГц', 'Гц',
    'мкФ', 'нФ', 'пФ', 'мГн', 'Гн', 'МПа', 'кПа', 'Па', 'мкс', 'мс', 'нс', 'пс',
    'мин', 'м²', 'м³', 'мм²', 'мм³', 'см²', 'см³', 'м2', 'м3', 'дБ', 'Дж',
    'м', 'г', 'т', 'А', 'A', 'В', 'V', 'К', 'K', 'Н', 'N', 'Ф', 'с', 's', 'ч', '%', '°',
)
_SPACE = r'[ \u00a0\u202f]'
_UNSIGNED = r'(?:\d{1,3}(?:[ \u00a0]\d{3})+|\d+)(?:[.,]\d+)?(?:[eE][+−-]?\d+)?'
_NUMBER = r'[+−-]?' + _UNSIGNED
_VALUE = r'(?:\(' + _SPACE + r'*' + _NUMBER + _SPACE + r'*±' + _SPACE + r'*' + _NUMBER + _SPACE + r'*\)|' + _NUMBER + r'\)?)'
_UNIT = '|'.join(re.escape(u).replace(r'\ ', _SPACE + '+') for u in sorted(UNITS, key=len, reverse=True))
QUANTITY = re.compile(r'(?<![\w./\\−-])(?P<value>' + _VALUE + r')(?P<gap>' + _SPACE + r'+)(?P<unit>' + _UNIT + r')(?![\w°/²³])')


@dataclass(frozen=True)
class UnitSpacingReport:
    quantities: int
    spaces: int
    warnings: tuple[str, ...]


def bind_units(document: Any) -> UnitSpacingReport:
    """Apply an exact node/offset whitespace ledger; all other text must match."""
    text_tags = {W+'t', W+'instrText', W+'delText'}
    before = [(n, n.text or '') for n in document.iter() if n.tag in text_tags]
    edits: dict[Any, set[int]] = {}
    quantities = 0
    warnings: list[str] = []
    body = document.find(W+'body')
    if body is None:
        return UnitSpacingReport(0,0,())
    for paragraph in body.findall('.//w:p',NS):
        # Keep fields, text boxes, tracked edits and embedded content opaque.
        if (any(a.tag in {W+'txbxContent',W+'del',W+'ins',W+'sdt',W+'fldSimple'} for a in paragraph.iterancestors())
                or paragraph.xpath('.//w:fldChar | .//w:instrText | .//w:fldSimple | .//w:del | .//w:ins | .//w:drawing | .//w:pict | .//w:object | .//w:hyperlink',namespaces=NS)):
            continue
        # Tabs/manual breaks are segment boundaries, never silently joined.
        tokens = paragraph.xpath('./w:r/w:t | ./w:r/w:tab | ./w:r/w:br | ./w:r/w:cr',namespaces=NS)
        segments: list[list[Any]] = [[]]
        for node in tokens:
            if node.tag == W+'t':
                segments[-1].append(node)
            else:
                segments.append([])
        for nodes in segments:
            content = ''.join(n.text or '' for n in nodes)
            locations = [(n,i) for n in nodes for i in range(len(n.text or ''))]
            for match in QUANTITY.finditer(content):
                # Distinguish a year abbreviation from grams, and a Russian
                # preposition from seconds. Ambiguous grammar stays for review.
                unit, value = match['unit'], match['value']
                rest = content[match.end():]
                if unit == 'г' and re.fullmatch(r'(?:19|20)\d{2}',value) and rest.startswith('.'):
                    continue
                if unit == 'с' and re.match(_SPACE + r'+[А-Яа-яЁё]',rest):
                    warnings.append('Проверить неоднозначное «с» после числа: возможны секунды или предлог; текст сохранён.')
                    continue
                offsets = [i for i in range(match.start(),match.end()) if content[i]==' ']
                if not offsets:
                    continue
                for offset in offsets:
                    node, local = locations[offset]
                    edits.setdefault(node,set()).add(local)
                quantities += 1
        # Report direct manual line breaks between otherwise recognized pairs.
        joined = ''.join((n.text or '') if n.tag==W+'t' else '\n' for n in tokens)
        for match in QUANTITY.finditer(joined.replace('\n',' ')):
            if '\n' in joined[match.start():match.end()]:
                warnings.append('Ручной перенос/табуляция разделяет числовое значение и единицу; требуется проверка без изменения структуры.')
                break
    expected: dict[Any,str] = {}
    for node, text in before:
        node_offsets = edits.get(node,set())
        if any(offset >= len(text) or text[offset]!=' ' for offset in node_offsets):
            raise ValueError('Недопустимая замена при связывании единиц измерения')
        expected[node] = ''.join(NBSP if i in node_offsets else char for i,char in enumerate(text))
        if node_offsets:
            node.text = expected[node]
    after = [(n,n.text or '') for n in document.iter() if n.tag in text_tags]
    if [n for n,_ in after] != [n for n,_ in before] or any(text!=expected[n] for n,text in after):
        raise ValueError('При связывании единиц изменён текст вне разрешённых пробелов')
    return UnitSpacingReport(quantities,sum(map(len,edits.values())),tuple(dict.fromkeys(warnings)))
