"""Conservative measurements of existing DrawingML frames, never redraw artwork.

Dimensions refer to recognized non-rotated group geometry, not the page origin.
Candidate form recognition is not certification of every field/line or template.
VML/raster-only, transformed/ambiguous and unrecognized geometry require review.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import re
from xml.etree import ElementTree as E
from zipfile import ZipFile

from document_inspection import W, _active, _parse
from tu_validation import DocumentCheck, _read

SOURCE='2fdb4e0c5dac26f5824dbdb8aafd0f20cacc1a0490222e3ee6d016c0b9df2094'
A='{http://schemas.openxmlformats.org/drawingml/2006/main}'
WP='{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}'
WPG='{http://schemas.microsoft.com/office/word/2010/wordprocessingGroup}'
WPS='{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}'
R='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
REL='{http://schemas.openxmlformats.org/package/2006/relationships}'
EMU=36000.0


@dataclass(frozen=True)
class ShapeBox:
    x: float
    y: float
    width: float
    height: float
    geometry: str
    text: str
    line_width: float


@dataclass(frozen=True)
class FrameMeasurement:
    width_mm: float
    height_mm: float
    stamp_height_mm: float | None
    candidate_form: str
    stroke_widths_mm: tuple[float,...]
    unmeasured_groups: int


def _int(node: E.Element | None,key: str) -> int:
    if node is None:raise ValueError('Отсутствует геометрия')
    value=int(node.attrib[key])
    if abs(value)>1_000_000_000:raise ValueError('Координаты вне поддерживаемого диапазона')
    return value


def _transformed(xfrm: E.Element) -> bool:
    return xfrm.get('rot','0')!='0' or any(xfrm.get(k,'0') not in {'0','false','off'} for k in ('flipH','flipV'))


def _walk(node: E.Element,ox: float,oy: float,sx: float,sy: float,boxes: list[ShapeBox],issues: list[str]) -> None:
    if len(boxes)>2048:raise ValueError('Слишком много фигур в группе')
    group=node.find(WPG+'grpSpPr/'+A+'xfrm')
    if group is not None:
        if _transformed(group):raise ValueError('Поворот/отражение группы не поддерживается')
        off,ext,child,ch_ext=[group.find(A+t) for t in ('off','ext','chOff','chExt')]
        if child is None or ch_ext is None:
            raise ValueError('Неопределённое преобразование линии/рамки')
        ex,ey,cx,cy=[_int(n,k) for n,k in ((ext,'cx'),(ext,'cy'),(ch_ext,'cx'),(ch_ext,'cy'))]
        if min(ex,ey,cx,cy)<=0:raise ValueError('Нулевая геометрия группы')
        tx,ty=ex/cx,ey/cy
        nx=ox+sx*(_int(off,'x')-_int(child,'x')*tx)
        ny=oy+sy*(_int(off,'y')-_int(child,'y')*ty)
        for member in node:
            start=len(boxes)
            try:
                _walk(member,nx,ny,sx*tx,sy*ty,boxes,issues)
            except (KeyError,ValueError,ZeroDivisionError):
                del boxes[start:]
                issues.append('Неизмеренная дочерняя группа/фигура')
        return
    if node.tag!=WPS+'wsp':return
    xfrm=node.find(WPS+'spPr/'+A+'xfrm')
    if xfrm is None or _transformed(xfrm):return
    off,ext=xfrm.find(A+'off'),xfrm.find(A+'ext')
    width,height=_int(ext,'cx'),_int(ext,'cy')
    if min(width,height)<0:raise ValueError('Отрицательный размер')
    geom=node.find(WPS+'spPr/'+A+'prstGeom')
    line=node.find(WPS+'spPr/'+A+'ln')
    weight=_int(line,'w') if line is not None and 'w' in line.attrib and line.find(A+'noFill') is None else 0
    boxes.append(ShapeBox(ox+sx*_int(off,'x'),oy+sy*_int(off,'y'),sx*width,sy*height,
                         geom.get('prst','') if geom is not None else '',
                         ''.join(n.text or '' for n in node.iter(W+'t')).strip(),weight*min(sx,sy)))


def measure_header(root: E.Element) -> tuple[FrameMeasurement,...]:
    results=[]
    for anchor in root.iter(WP+'anchor'):
        group=anchor.find('.//'+WPG+'wgp')
        extent=anchor.find(WP+'extent')
        if group is None:continue
        xfrm=group.find(WPG+'grpSpPr/'+A+'xfrm')
        try:
            size=xfrm.find(A+'ext') if xfrm is not None else None
            sx,sy=_int(extent,'cx')/_int(size,'cx'),_int(extent,'cy')/_int(size,'cy')
            if min(sx,sy)<=0:continue
            boxes: list[ShapeBox]=[]
            issues: list[str]=[]
            _walk(group,0,0,sx,sy,boxes,issues)
        except (KeyError,ValueError,ZeroDivisionError):
            continue
        frames=[b for b in boxes if b.geometry=='rect' and not b.text and b.line_width>0
                and 160<=b.width/EMU<=215 and 240<=b.height/EMU<=310]
        if len(frames)!=1 or not any('ТУ' in b.text for b in boxes):continue
        frame=frames[0]
        lines=[b for b in boxes if b.geometry=='line' and b.line_width>0 and b.height/EMU<.15
               and abs(b.width-frame.width)/EMU<.75 and abs(b.x-frame.x)/EMU<.75
               and frame.y+frame.height-60*EMU<b.y<frame.y+frame.height]
        height=(frame.y+frame.height-min(b.y for b in lines))/EMU if lines else None
        candidate=('похожа на 2' if height is not None and abs(height-40)<=.5 else
                   'похожа на 2а' if height is not None and abs(height-15)<=.5 else 'не определена')
        results.append(FrameMeasurement(round(frame.width/EMU,3),round(frame.height/EMU,3),
            round(height,3) if height is not None else None,candidate,
            tuple(sorted({round(b.line_width/EMU,3) for b in boxes if b.line_width>0})),len(issues)))
    return tuple(results)


def review_stamps(raw: bytes,document_form: str) -> tuple[DocumentCheck,...]:
    document,_=_read(raw)
    checks=[]
    with ZipFile(BytesIO(raw)) as package:
        relationships=_parse(package.read('word/_rels/document.xml.rels'))
        used={n.get(R+'id') for n in document.iter(W+'headerReference')}
        parts=[]
        for rel in relationships:
            target=rel.get('Target','')
            if (rel.get('Id') in used and rel.get('TargetMode')!='External'
                    and re.fullmatch(r'header\d+\.xml',target) and 'word/'+target in package.namelist()):
                parts.append('word/'+target)
        for part in sorted(set(parts)):
            root=_active(_parse(package.read(part)))
            text=' '.join(n.text or '' for n in root.iter(W+'t'))
            measured=measure_header(root)
            if not measured:
                checks.append(DocumentCheck('stamp-geometry-'+part,'ГОСТ Р 2.104-2023, Б.2–Б.5; PDF стр. 15–19',
                    'требует проверки','Распознанная геометрия активного колонтитула '+part,
                    'Однозначная рамка DrawingML не измерена. VML/растровые, повёрнутые, неоднозначные и иные формы не угадываются. Исходная геометрия сохранена.'))
                continue
            for i,m in enumerate(measured):
                difference=m.width_mm-185
                checks.append(DocumentCheck(f'stamp-geometry-{part}-{i}','ГОСТ Р 2.104-2023, Б.2–Б.3; PDF стр. 15–17',
                    'требует проверки' if abs(difference)>.5 or m.candidate_form=='не определена' or m.unmeasured_groups else 'наблюдение',
                    'Неизменённая геометрия группы DrawingML в '+part+'; положение относительно края страницы отдельно не измерено',
                    f'Ширина рамки {m.width_mm:g} мм; высота {m.height_mm:g} мм; высота распознанного нижнего блока {m.stamp_height_mm} мм; '
                    f'форма {m.candidate_form}. Для форм 2/2а ширина основного блока 185 мм, высота 40/15 мм. '
                    f'Разность ширины с 185 мм: {difference:+.3f} мм. Порог 0,5 мм здесь только порог выявления кандидата, не нормативный допуск. '
                    f'Наблюдаемые толщины линий {m.stroke_widths_mm} мм; соответствие типов/толщин по ГОСТ 2.303 этим не подтверждено. '
                    f'Неизмеренных дочерних групп/фигур: {m.unmeasured_groups}; это частичное измерение, не проверка всей формы. '
                    'Графы, дополнительные поля, выбранная форма и масштаб требуют проверки; рисунок не растягивался.'))
            dates=re.findall(r'\b\d{2}\.\d{2}\.(?:\d{4}|\d{2})\b',text)
            labels=[label for label in ('Разраб.','Н. контр.','Н.контр.','Лист','Листов') if label in text]
            checks.append(DocumentCheck('stamp-requisites-'+part,'ГОСТ Р 2.104-2023, 5.7–5.8, таблица 1; PDF стр. 5–8',
                'требует проверки','Реквизиты активного колонтитула '+part,
                f'Найденные метки {labels}; записи дат {sorted(set(dates))}. '
                'Наличие метки не подтверждает заполнение ФИО/подписи. Проверить обязательные действия разработчика/нормоконтроля, '
                'обозначение, наименование, номер листа и общее число листов по роли графы. '
                'Для бумажной формы в графах 13, 18, 20, 23 двухзначный год допускается; другие даты нельзя оценить без определения графы. '
                'Подписи, даты, литеры и реквизиты не придумывались.'))
    if not checks:
        checks.append(DocumentCheck('stamp-no-supported-headers','ГОСТ Р 2.104-2023, 5.1, Б.2–Б.5; PDF стр. 3–4, 15–19',
            'требует проверки','Активные колонтитулы DOCX','Поддерживаемые колонтитулы не найдены; бланк не создаётся и соответствие не устанавливается.'))
    checks.append(DocumentCheck('stamp-form-choice','ГОСТ Р 2.104-2023, 5.3, 5.6, Б.4; PDF стр. 4, 17–19',
        'требует подтверждения','Выбранное представление документа',
        'Представление: '+document_form+'. Печатный макет с рамками не приравнивается к формальному электронному КД. '
        'Существующие рамки и дополнительные поля сохранены. Вариант без рамки, двусторонняя форма 2б, '
        'организационные дополнения и согласование заказчика не выбираются автоматически.'))
    return tuple(checks)
