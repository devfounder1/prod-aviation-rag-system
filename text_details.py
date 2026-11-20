"""Bounded, read-only findings for remaining selected R 2.105 conditions.

Literal candidates are not engineering conclusions. Locations address exact
DOCX body blocks/cells, not rendered page numbers. Never rewrite values,
references, abbreviations, notes or formulas from these observations.
"""
from __future__ import annotations

from dataclasses import dataclass
import copy
import re
from typing import Any
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as E

from document_inspection import W, _active, _parse
from text_review import visible_text
from tu_validation import DocumentCheck, _read


@dataclass(frozen=True)
class LocatedText:
    location: str
    text: str
    in_table: bool


def locations(raw: bytes) -> tuple[LocatedText,...]:
    document,_=_read(raw);document=_active(document)
    body=document.find(W+'body');assert body is not None
    with ZipFile(BytesIO(raw)) as package:
        styles=_parse(package.read('word/styles.xml')) if 'word/styles.xml' in package.namelist() else None
    # Conservatively exclude paragraphs using hidden or unresolved style chains.
    definitions={s.get(W+'styleId',''):s for s in styles.findall(W+'style')} if styles is not None else {}
    default_style=next((key for key,s in definitions.items()
                        if s.get(W+'type')=='paragraph' and s.get(W+'default') in {'1','true','on'}),'')
    def hidden(key: str) -> bool:
        seen: set[str]=set()
        while key:
            if key in seen or key not in definitions:return True
            seen.add(key);style=definitions[key]
            for name in ('vanish','webHidden','specVanish'):
                n=style.find(W+'rPr/'+W+name)
                if n is not None and n.get(W+'val','1') not in {'0','false','off'}:return True
            base=style.find(W+'basedOn');key=base.get(W+'val','') if base is not None else ''
        return False
    def text(p: Any) -> str:
        refs=list(p.iter(W+'pStyle'))+list(p.iter(W+'rStyle'))
        if any(hidden(n.get(W+'val','')) for n in refs):return ''
        if p.find(W+'pPr/'+W+'pStyle') is None and default_style and hidden(default_style):return ''
        if styles is not None and any(n.get(W+'val','1') not in {'0','false','off'}
                for name in ('vanish','webHidden','specVanish')
                for n in styles.findall(W+'docDefaults/'+W+'rPrDefault/'+W+'rPr/'+W+name)):return ''
        # A partial paragraph could join visible fragments into a fictitious token.
        if any(n.tag in {W+'hyperlink',W+'sdt'} for n in p.iter()):return ''
        visible=copy.deepcopy(p)
        for run in visible.findall(W+'r'):
            if any(n.tag in {W+'vanish',W+'webHidden',W+'specVanish'} and n.get(W+'val','1') not in {'0','false','off'} for n in run.iter()):
                # A separator prevents joining tokens across omitted hidden runs.
                run.clear();separator=E.SubElement(run,W+'t');separator.text=' '
        return visible_text(visible)
    found=[]
    for i,block in enumerate(body,1):
        if block.tag==W+'p':
            value=text(block)
            if value:found.append(LocatedText(f'b{i}',value,False))
        elif block.tag==W+'tbl':
            for j,row in enumerate(block.findall(W+'tr'),1):
                for k,cell in enumerate(row.findall(W+'tc'),1):
                    for n,p in enumerate(cell.findall(W+'p'),1):
                        value=text(p)
                        if value:found.append(LocatedText(f'b{i}/r{j}/c{k}/p{n}',value,True))
    return tuple(found)


def _evidence(rows: list[LocatedText], limit: int=12) -> str:
    samples='; '.join(f'{r.location}: {r.text[:180]}'+(' [фрагмент сокращён]' if len(r.text)>180 else '') for r in rows[:limit])
    return f'Найдено {len(rows)}. '+(samples or 'Кандидатов в поддерживаемой области не найдено.')+(
        f' [Вывод ограничен: показаны {limit} из {len(rows)}.]' if len(rows)>limit else '')


def review_details(raw: bytes) -> tuple[DocumentCheck,...]:
    rows=locations(raw);checks=[]
    def add(key: str,clause: str,title: str,selected: list[LocatedText],note: str) -> None:
        checks.append(DocumentCheck('text-detail-'+key,'ГОСТ Р 2.105-2019, '+clause,
            'требует проверки' if selected else 'наблюдение',title,
            _evidence(selected)+' '+note+' Проверка только чтением; отсутствие кандидата не означает соответствие.'))
    add('note-label','6.12.3; PDF стр. 28','Пунктуация одиночной метки примечания',
        [r for r in rows if re.match(r'^Примечание\s*:',r.text)],
        'Для одиночного примечания предусмотрено тире. Пунктуация исходника сохранена для согласования.')
    add('note-requirements','6.12.1; PDF стр. 28','Слова требований внутри явно обозначенного примечания',
        [r for r in rows if r.text.startswith('Примечание') and re.search(r'\b(?:долж\w*|необходимо|требуется|запрещается)\b',r.text,re.I)],
        'Примечание не должно содержать требований. Ключевые слова лишь указывают место для смыслового решения; продолжения групп могут быть не распознаны.')
    add('reference-format','6.11.5; PDF стр. 28','Повреждённые буквальные ссылки на пункт',
        [r for r in rows if re.search(r'\bп\.\s*\d+(?:\.\d+)+\.\s+\S+\s+\d+\s+ТУ',r.text)],
        'Номер не восстанавливается по соседним ссылкам; требуется сверка исходной методики.')
    add('unit-series','6.16.4–6.16.5; PDF стр. 30','Ряды с повторением единиц',
        [r for r in rows if not r.in_table and re.search(r'\d\s*мА\s*,\s*\d\s*мА',r.text)],
        'В ряду единицу указывают после последнего значения. Сначала отличить ряд от перечисления отдельных измерений; числа не меняются. Для °C, %, ° в диапазоне есть исключение.')
    add('formula-text','6.10.1–6.10.5, 6.15.4; PDF стр. 26, 29','Буквальные математические записи, включая ячейки',
        [r for r in rows if re.search(r'[±=]',r.text) and re.search(r'(?<![A-Za-zА-Яа-я])[UIτ](?:уст)?(?![A-Za-zА-Яа-я])|Кр\s*\+',r.text)],
        'Проверить обозначения, пояснения и единицы по первичным данным. Это кандидаты, а не распознанные самостоятельные формулы: нельзя автоматически назначать им номера или дописывать пояснения.')
    add('where-colon','6.10.1; PDF стр. 26','Начало пояснений символов',
        [r for r in rows if re.match(r'^где\s*:',r.text,re.I)],'Первая строка пояснений начинается словом «где» без двоеточия.')
    add('normative-refs','6.11.1–6.11.4; PDF стр. 26–28','Буквальные ссылки на нормативные документы',
        [r for r in rows if re.search(r'\b(?:ГОСТ|ОСТ|СТО)\s+[РP]?\s*\d',r.text)],
        'Наличие года/перечня, точная редакция и договорная применимость проверяются отдельно; код изделия и ссылки на ОТУ не считаются ГОСТами.')
    add('abbreviations','5.2.3, 6.15.1–6.15.4; PDF стр. 7, 29','Кандидаты специальных сокращений',
        [r for r in rows if re.search(r'\b(?:МДПИ|ОТК|ОТУ|ЗИП|СИ|ШОИ\d*)\b',r.text)],
        'Не все заглавные обозначения являются сокращениями. Допустимость и полнота пояснений требуют ГОСТ Р 2.316 и КД; расшифровки не придумываются.')
    add('registration','5.1.8; PDF стр. 7','Лист регистрации изменений',
        [r for r in rows if r.text=='Лист регистрации изменений'],
        'Наличие заголовка не проверяет форму по Р 2.503/Р 21.101 и факт внесения изменений; допускается оформление при внесении изменений.')
    return tuple(checks)
