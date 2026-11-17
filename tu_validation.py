"""Read-only measurements for a TU candidate; never invent missing technical text.

Measurements and heading observations are deliberately separate from normative
conformity: ГОСТ 2.114 clause 5.1.2 allows a developer-defined section composition.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re
import tempfile
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from document_inspection import W, inspect_docx, _parse

TU_SOURCE_SHA256 = '556c15185dd0c00e2310d9b96113b252c27788d1e29215005b49e533a18f45a5'


@dataclass(frozen=True)
class DocumentCheck:
    check_id: str
    reference: str
    status: str
    scope: str
    evidence: str


def _text(node: ET.Element) -> str:
    return re.sub(r'\s+', ' ', ''.join(n.text or '' for n in node.iter(W+'t'))).strip()


def _key(text: str) -> str:
    return re.sub(r'^\d+(?:\.\d+)*[.)]?\s+', '', text).casefold().replace('ё','е').strip()


def _read(raw: bytes) -> tuple[ET.Element, dict[str,str]]:
    # Reuse the bounded package/DTD/macro inspection before any XML analysis.
    with tempfile.TemporaryDirectory(prefix='butuz-tu-check-') as folder:
        path=Path(folder)/'candidate.docx';path.write_bytes(raw)
        evidence=inspect_docx(path)
        if evidence.has_macros:
            raise ValueError('Документ содержит макросы')
    with ZipFile(BytesIO(raw)) as package:
        document=_parse(package.read('word/document.xml'))
        roles: dict[str,str]={}
        if 'word/styles.xml' in package.namelist():
            for style in _parse(package.read('word/styles.xml')).iter(W+'style'):
                name=style.find(W+'name')
                if name is not None:
                    roles[style.get(W+'styleId','')]=name.get(W+'val','').lower().replace(' ','')
    return document,roles


def validate_tu(raw: bytes) -> tuple[DocumentCheck,...]:
    """Report observable properties. Never decide safety/content or rewrite a TU."""
    try:
        document,roles=_read(raw)
    except (ValueError, OSError, KeyError) as exc:
        return (DocumentCheck('input','Проверяемый DOCX','не поддерживается','Пакет документа',
                              'Измерения не выполнены: '+str(exc)[:300]),)
    body=document.find(W+'body')
    assert body is not None  # inspect_docx already verified this.
    blocks=list(body)
    paragraphs=body.findall(W+'p')
    headings: list[tuple[int,str]]=[]
    body_spacing: list[tuple[int,bool]]=[]
    main=False
    for index,p in enumerate(paragraphs,1):
        plain=_text(p)
        if plain.startswith('Приложение '):
            break
        style=p.find('w:pPr/w:pStyle',{'w':W[1:-1]})
        role=roles.get(style.get(W+'val',''),'unknown') if style is not None else 'normal'
        if role in {'heading1','заголовок1'} and plain:
            headings.append((index,plain));main=True
        if not main or not plain or role not in {'normal','bodytext','heading3','heading4','заголовок3','заголовок4'}:
            continue
        position=blocks.index(p)
        if (re.match(r'^(?:Таблица|Продолжение\s+таблицы)\s+[А-ЯA-Zа-яa-z]?\.?\d+',plain,re.I)
                and position+1<len(blocks) and blocks[position+1].tag==W+'tbl'):
            continue  # Proven caption, not ordinary prose mentioning a table.
        if any(p.find('.//'+W+tag) is not None for tag in ('drawing','pict','object','fldChar')):
            continue
        spacing=p.find('w:pPr/w:spacing',{'w':W[1:-1]})
        correct=(spacing is not None and spacing.get(W+'line')=='360' and
                 spacing.get(W+'lineRule','auto')=='auto' and
                 spacing.get(W+'before','0')=='0' and spacing.get(W+'after','0')=='0' and
                 spacing.get(W+'beforeAutospacing','0') in {'0','false','off'} and
                 spacing.get(W+'afterAutospacing','0') in {'0','false','off'})
        body_spacing.append((index,correct))
    sizes=[]
    for section in document.iter(W+'sectPr'):
        size=section.find(W+'pgSz')
        if size is not None:
            try:
                sizes.append(tuple(sorted(round(int(size.get(W+v,''))*25.4/1440,2) for v in ('w','h'))))
            except ValueError:
                sizes.append((0.,0.))
        else:
            sizes.append((0.,0.))  # Unresolved inheritance must not become a positive measurement.
    a4=bool(sizes) and all(abs(w-210)<.2 and abs(h-297)<.2 for w,h in sizes)
    result=[DocumentCheck('page-size','ГОСТ 2.114-2016, 4.8; PDF стр. 6',
        'измерено' if a4 else 'требует проверки','Только размер страниц DOCX; штампы/режим печати не проверены',
        f'Размеры секций, мм: {sizes}. Допуск 0,2 мм используется только для округления единиц OOXML.'),
        DocumentCheck('body-spacing','Настройка профиля 1,5; ГОСТ Р 2.105-2019, 5.1.2',
        'измерено' if body_spacing and all(ok for _,ok in body_spacing) else 'требует проверки',
        'Распознанные обычные/номерные абзацы после первого основного раздела, до приложений; без таблиц, их подписей и объектов',
        f'Абзацев: {len(body_spacing)}; интервал 1,5 и нулевые до/после: {sum(ok for _,ok in body_spacing)}. '
        f'Неподтверждённые индексы: {[i for i,ok in body_spacing if not ok][:30]}.'),
        DocumentCheck('intro','ГОСТ 2.114-2016, 5.2.1–5.2.3; PDF стр. 7','наблюдение',
        'Только обнаружение вводной части; соответствие основному КД и полнота не проверены',
        '\n'.join(f'Абзац {i}: {_text(p)[:450]}' for i,p in enumerate(paragraphs,1)
                  if _text(p).casefold().startswith('настоящие технические условия')) or 'Вводная формула не обнаружена.')]
    groups=(('Технические требования',{'технические требования'}),
            ('Требования безопасности',{'требования безопасности'}),
            ('Требования охраны окружающей среды',{'требования охраны окружающей среды','охрана окружающей среды'}),
            ('Правила приёмки',{'правила приемки'}),
            ('Методы контроля (испытаний)',{'методы контроля','методы испытаний','требования контроля','методы контроля (испытаний)'}),
            ('Указания по эксплуатации',{'указания по эксплуатации','эксплуатация','хранение и транспортирование'}),
            ('Гарантии изготовителя',{'гарантии изготовителя'}))
    for title,aliases in groups:
        found=[(i,t) for i,t in headings if _key(t) in aliases]
        result.append(DocumentCheck('section-'+str(len(result)),'ГОСТ 2.114-2016, 5.1.1–5.1.2; PDF стр. 7',
            'наблюдение' if found else 'требует подтверждения',
            title+' — только заголовки основных разделов, не оглавление и не смысловой анализ',
            repr(found) if found else 'Отдельный раздел не обнаружен. По 5.1.2 состав может быть изменён '
            'разработчиком; нужны ТЗ/решение разработчика. Отсутствие заголовка не признано нарушением.'))
    full='\n'.join(_text(p) for p in paragraphs)
    refs=re.findall(r'\b[А-ЯA-Z]{4}\.\d{6}\.\d{3}\s*ТУ\b',full)
    result.append(DocumentCheck('references','ГОСТ 2.114-2016, 4.4 и 5.7.16; PDF стр. 6, 12',
        'требует подтверждения','Ссылочные документы; содержание и применимость не проверены',
        'Обнаруженные обозначения ТУ: '+', '.join(sorted(set(refs)))+
        '. Для проверки требований по ссылкам нужны соответствующие документы; текст по ссылке не придумывается.'))
    return tuple(result)


def verify_preview(docx: bytes, pdf: bytes) -> int:
    """Fail if an explicit editable continuation caption disappears in final PDF.

    This does not prove table row fit, diagram correctness or complete compliance.
    """
    document,_=_read(docx)
    body=document.find(W+'body');assert body is not None
    blocks=list(body)
    expected=Counter(_text(p) for i,p in enumerate(blocks[:-1]) if p.tag==W+'p' and blocks[i+1].tag==W+'tbl'
                     and re.fullmatch(r'Продолжение\s+таблицы\s+[А-ЯA-Zа-яa-z]?\.?\d+(?:\.\d+)*',_text(p),re.I))
    if not expected:
        return 0
    import pdfplumber
    observed: dict[str,set[int]]={label:set() for label in expected}
    with pdfplumber.open(BytesIO(pdf)) as rendered:
        if len(rendered.pages)>60:
            raise ValueError('Слишком много страниц итогового PDF')
        for number,page in enumerate(rendered.pages):
            for caption in expected:
                pattern=r'\s+'.join(re.escape(word) for word in caption.split())+r'(?![\d.])'
                for hit in page.search(pattern):
                    if hit['top']<0 or hit['bottom']>page.height or hit['x0']<0 or hit['x1']>page.width:
                        raise ValueError('Подпись продолжения выходит за страницу PDF')
                    observed[caption].add(number)
    if any(len(observed[label])<count for label,count in expected.items()):
        raise ValueError('В итоговом PDF отсутствует подпись продолжения таблицы; сохранение остановлено')
    return sum(expected.values())
