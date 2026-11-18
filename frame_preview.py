"""Observe axis-aligned existing A4 frame outlines in the exact rendered preview.

Read-only: no template selection, drawing replacement or normative pass verdict.
Only an unambiguous full-page closed rectangular outline near the frame area
is measured; unknown/raster/rotated/complex geometry remains for visual review.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import pdfplumber

PT_MM=25.4/72


@dataclass(frozen=True)
class PreviewFrame:
    page: int
    left_mm: float
    top_mm: float
    width_mm: float
    height_mm: float
    stamp_height_mm: float | None


def _rectangle(shape: dict[str,Any]) -> bool:
    points=shape.get('pts',[])
    if not 4<=len(points)<=12:return False
    if any(c[0] not in {'m','l','h'} for c in shape.get('path',[])):return False
    x0,x1,top,bottom=(float(shape[k]) for k in ('x0','x1','top','bottom'))
    def close(a: float,b: float) -> bool:
        return abs(a-b)<.1
    if not (close(points[0][0],points[-1][0]) and close(points[0][1],points[-1][1])):return False
    if not all(close(a[0],b[0]) or close(a[1],b[1]) for a,b in zip(points,points[1:])):return False
    return all(any(close(x,px) and close(y,py) for px,py in points) for x,y in ((x0,top),(x1,top),(x1,bottom),(x0,bottom)))


def observe_frames(raw: bytes) -> tuple[PreviewFrame,...]:
    if not raw.startswith(b'%PDF-') or len(raw)>32*1024*1024:raise ValueError('Недопустимый PDF предпросмотра')
    rows=[]
    with pdfplumber.open(BytesIO(raw)) as pdf:
        if not 1<=len(pdf.pages)<=60:raise ValueError('Слишком много страниц PDF')
        for number,page in enumerate(pdf.pages,1):
            if abs(page.width*PT_MM-210)>1 or abs(page.height*PT_MM-297)>1:continue
            candidates=[]
            for shape in [*page.rects,*page.curves]:
                if not shape.get('stroke',False):continue
                if not (14<=shape['x0']*PT_MM<=30 and 0<=shape['top']*PT_MM<=12
                        and 175<=shape['width']*PT_MM<=190 and 270<=shape['height']*PT_MM<=292):continue
                if shape['object_type']=='curve' and not _rectangle(shape):continue
                candidates.append(shape)
            if len(candidates)!=1:continue
            frame=candidates[0];lines=[]
            for shape in [*page.lines,*page.rects]:
                if not shape.get('stroke',False):continue
                if (abs(shape['width']-frame['width'])*PT_MM<.75 and abs(shape['x0']-frame['x0'])*PT_MM<.75
                        and (frame['bottom']-shape['bottom'])*PT_MM<.75
                        and 5<shape['height']*PT_MM<60):
                    lines.append(shape['top'])
                elif (abs(shape['width']-frame['width'])*PT_MM<.75 and abs(shape['x0']-frame['x0'])*PT_MM<.75
                        and shape['height']*PT_MM<.15 and 5<(frame['bottom']-shape['top'])*PT_MM<60):
                    lines.append(shape['top'])
            height=(frame['bottom']-min(lines))*PT_MM if lines else None
            if height is not None and min(abs(height-15),abs(height-40))>1:
                height=None  # A full-page fixed form is not a 2/2а main block.
            rows.append(PreviewFrame(number,round(frame['x0']*PT_MM,3),round(frame['top']*PT_MM,3),
                round(frame['width']*PT_MM,3),round(frame['height']*PT_MM,3),round(height,3) if height is not None else None))
    return tuple(rows)


def frame_warnings(raw: bytes) -> tuple[str,...]:
    frames=observe_frames(raw)
    groups: dict[tuple[float,float,float | None],list[int]]=defaultdict(list)
    for row in frames:groups[(round(row.width_mm,2),round(row.height_mm,2),round(row.stamp_height_mm,2) if row.stamp_height_mm is not None else None)].append(row.page)
    lines=[]
    for (width,height,stamp),pages in groups.items():
        lines.append(f'Рамка PDF, страницы {pages}: ширина {width:g} мм, высота {height:g} мм, нижний блок '+(f'{stamp} мм. ' if stamp is not None else 'не определён. ')+
                     'У форм 2/2а Р 2.104 ширина основного блока 185 мм, высота 40/15 мм; выбор формы и всех граф требует проверки. '
                     'Это измерение распознанного контура, не заключение о соответствии; исходная графика не менялась.')
    if not frames:lines.append('Однозначные векторные контуры рамок A4 в PDF не измерены; нужна визуальная проверка, в том числе растровых/сложных форм.')
    else:lines.append('Рамки измерены только на перечисленных страницах; остальные формы/титул, типы линий, подписи и реквизиты требуют отдельной проверки.')
    return tuple(lines)
