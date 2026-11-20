"""Read-only Р 2.105 observations; never rewrite or certify technical content.

Only visible direct body paragraphs are used for literal internal references.
TOC, hidden runs, drawings, revisions and opaque formula objects are excluded.
References may point outside this document: unresolved is not an automatic error.
"""
from __future__ import annotations

from collections import Counter
from io import BytesIO
import re
from typing import Any
from zipfile import ZipFile

from document_inspection import W, _active, _parse
from tu_validation import DocumentCheck, _read

SOURCE = 'c3bb3ae4a47c190004bc48225dc8bce53e9579e8b05379a1429d749e28d250ad'
NUMBER = r'(?:[А-ЯA-Z]\.)?\d+(?:\.\d+)*'
REFS = {
    'таблица': re.compile(r'\bтаблиц(?:а|ы|е|у|ей)\s+('+NUMBER+r')(?!\w|\.\d)', re.I),
    'рисунок': re.compile(r'\bрисун(?:ок|ка|ке|ку|ком)\s+('+NUMBER+r')(?!\w|\.\d)', re.I),
    'приложение': re.compile(r'\bприложени(?:е|я|и|ю|ем)\s+([А-ЯA-Z]|\d+)(?!\w|\.\d)', re.I),
}


def visible_text(paragraph: Any) -> str:
    """Known plain visible text only; do not extract alternative/drawing text."""
    if any(paragraph.find('.//'+W+t) is not None for t in ('drawing','pict','object','del','ins','fldChar','fldSimple','instrText')):
        return ''
    result: list[str]=[]
    for run in paragraph.findall(W+'r'):
        if any((n:=run.find(W+'rPr/'+W+t)) is not None and n.get(W+'val','1') not in {'0','false','off'}
               for t in ('vanish','webHidden','specVanish')):
            continue
        result.extend(n.text or '' for n in run.findall(W+'t'))
    return re.sub(r'\s+',' ',''.join(result)).strip()


def review_text(raw: bytes) -> tuple[DocumentCheck,...]:
    document,_=_read(raw)
    document=_active(document)
    body=document.find(W+'body')
    assert body is not None
    blocks=list(body)
    targets: dict[str,list[str]]={k:[] for k in REFS}
    texts: list[str]=[]
    for i,p in enumerate(blocks):
        if p.tag!=W+'p':continue
        text=visible_text(p)
        if not text:continue
        table=re.fullmatch(r'Таблица\s+('+NUMBER+r')(?:\s*[—–-]\s*.+)?',text)
        if table and i+1<len(blocks) and blocks[i+1].tag==W+'tbl':
            targets['таблица'].append(table[1]);continue
        figure=re.fullmatch(r'Рисунок\s+('+NUMBER+r')(?:\s*[—–-]\s*.+)?',text)
        if figure:
            # Only with a nearby actual graphic, not an ordinary sentence.
            graphic=any(any(q.find('.//'+W+t) is not None for t in ('drawing','pict','object'))
                        for q in blocks[max(0,i-8):i])
            if graphic:targets['рисунок'].append(figure[1]);continue
        appendix=re.match(r'^Приложение\s+([А-ЯA-Z]|\d+)\s*\((обязательное|рекомендуемое|справочное)\)',text)
        if appendix:targets['приложение'].append(appendix[1]);continue
        texts.append(text)
    checks=[]
    for kind,pattern in REFS.items():
        found=[m[1] for text in texts for m in pattern.finditer(text)]
        duplicates=[v for v,count in Counter(targets[kind]).items() if count>1]
        unresolved=sorted(set(found)-set(targets[kind]))
        unreferenced=sorted(set(targets[kind])-set(found))
        ref={'таблица':'6.8.2–6.8.3; PDF стр. 15–16','рисунок':'6.9.3; PDF стр. 24–25','приложение':'6.3.3–6.3.8; PDF стр. 9–10'}[kind]
        checks.append(DocumentCheck('text-references-'+kind,'ГОСТ Р 2.105-2019, '+ref,
            'требует проверки' if unresolved or duplicates or unreferenced else 'наблюдение',
            'Только буквальные ссылки и распознанные подписи основного текста; без оглавления/скрытого текста',
            f'{kind}: цели {targets[kind]}; ссылок {len(found)}; дубли целей {duplicates}; '
            f'ссылки без локальной цели {unresolved}; цели без обнаруженной ссылки {unreferenced}. '
            'Неопознанные/внешние ссылки и порядок размещения проверяет человек; это не заключение о соответствии.'))
    with ZipFile(BytesIO(raw)) as package:
        footnotes=0
        if 'word/footnotes.xml' in package.namelist():
            notes=_parse(package.read('word/footnotes.xml'))
            footnotes=sum(1 for n in notes.findall(W+'footnote') if n.get(W+'id','').lstrip('-').isdigit()
                          and int(n.get(W+'id','0'))>0 and n.get(W+'type','normal')=='normal')
        math_ns='{http://schemas.openxmlformats.org/officeDocument/2006/math}'
        equations=len(list(document.iter(math_ns+'oMath')))
        objects=len(list(document.iter(W+'object')))
    checks.append(DocumentCheck('text-formulas-footnotes','ГОСТ Р 2.105-2019, 6.10, 6.13; PDF стр. 26, 28–29',
        'требует проверки','Нативные структуры OOXML; изображённые/встроенные формулы этим не распознаются',
        f'Нативных формул {equations}, обычных сносок {footnotes}, активных OOXML-узлов object {objects}. '
        'Формулы/сноски не перенумеровываются и не переписываются. Проверить пояснения символов, переносы на знаках '
        'операций, скобки/выравнивание номеров, надстрочные знаки и постраничную нумерацию сносок. '
        'Нулевое число нативных структур не доказывает отсутствия формул/сносок на изображениях.'))
    checks.append(DocumentCheck('text-normative-references','ГОСТ Р 2.105-2019, 5.2, 6.11, 6.15–6.16; PDF стр. 7–8, 26–30',
        'требует проверки','Терминология, ссылочные редакции, единицы, точность и смысл условий',
        'Проверить одинаковое полное название на титуле/в штампе/первом упоминании, специальные сокращения, '
        'пояснения обозначений, разрешённость ссылок и наличие редакций в перечне. Числа, допуски, системы единиц, '
        'точность и инженерные формулировки автоматически не меняются; нужны исходные КД/ТЗ и ссылочные документы.'))
    checks.append(DocumentCheck('text-title-and-form','ГОСТ Р 2.105-2019, 6.1, 6.4–6.5, 7–9; PDF стр. 8, 11–13, 31–35',
        'требует подтверждения','Структура документа, титул/ЛУ, табличные документы и двустороннее копирование',
        'Дополнительные элементы определяет разработчик. Титул и лист утверждения сохраняются; их реквизиты, '
        'полномочия/подписи и необходимость отдельного ЛУ проверяются вручную. Раздел 7 не накладывается на весь текст '
        'ТУ из-за наличия таблиц. Двустороннее копирование и разбиение на книги не включены без выбора соответствующего представления.'))
    from text_details import review_details
    return (*checks,*review_details(raw))
