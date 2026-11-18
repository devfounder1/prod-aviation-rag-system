"""Selected Р 2.105 typography for existing notes, TOC and appendix headings.

No missing titles, references or technical prose are invented. Label tracking
may split one proven plain text run; an exact source-index ledger accounts for
the two fragments and permits no character changes. Fields/objects stay opaque.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import re
from typing import Any

from lxml import etree as ET  # type: ignore[import-untyped]

from document_elements import NS,W,_node,_set,_text,_section_bounds
from list_layout import _chain,_level
from standard_profiles import FormattingProfile

TEXT_TAGS={W+'t',W+'instrText',W+'delText'}
LABEL=re.compile(r'^(Примечание|Примечания|Пример|Примеры)(?=$|\s|[:—–-])')


@dataclass(frozen=True)
class TextSplit:
    index: int
    original: str
    first: str
    second: str


@dataclass(frozen=True)
class StructureReport:
    notes: int
    examples: int
    toc_entries: int
    appendix_headings: int
    splits: tuple[TextSplit,...]
    warnings: tuple[str,...]
    table_labels: int = 0


def expected_texts(before: list[tuple[str,str]],splits: tuple[TextSplit,...]) -> list[tuple[str,str]]:
    """Only accept exact, nonempty partitions of recorded original w:t nodes."""
    indexed={s.index:s for s in splits}
    if len(indexed)!=len(splits) or any(i<0 or i>=len(before) for i in indexed):
        raise ValueError('Неоднозначное разбиение текстового фрагмента')
    result=[]
    for i,(tag,value) in enumerate(before):
        split=indexed.get(i)
        if split is None:
            result.append((tag,value));continue
        if (tag!=W+'t' or split.original!=value or not split.first or not split.second
                or split.first+split.second!=value):
            raise ValueError('Изменён текст при оформлении метки')
        result.extend(((tag,split.first),(tag,split.second)))
    return result


def _plain(paragraph: Any) -> bool:
    return not bool(paragraph.xpath('.//w:fldChar | .//w:instrText | .//w:fldSimple | .//w:del | .//w:ins | .//w:drawing | .//w:pict | .//w:object | .//w:hyperlink',namespaces=NS))


def format_font(paragraph: Any,size: int,*,example: bool=False,bold: bool=False) -> None:
    # Number labels without a level-specific size inherit the paragraph mark.
    mark=_node(_node(paragraph,'pPr'),'rPr')
    _set(mark,'sz',val=str(size*2));_set(mark,'szCs',val=str(size*2))
    if example or bold:_set(mark,'b',val='1')
    if example:_set(mark,'i',val='1')
    for run in paragraph.findall(W+'r'):
        if run.find(W+'t') is None:
            continue
        rpr=_node(run,'rPr')
        hidden=rpr.find(W+'vanish')
        if rpr.find(W+'vertAlign') is not None or (hidden is not None and hidden.get(W+'val','1') not in {'0','false','off'}):
            continue
        _set(rpr,'sz',val=str(size*2));_set(rpr,'szCs',val=str(size*2))
        if example or bold:
            _set(rpr,'b',val='1')
        if example:
            _set(rpr,'i',val='1')


def _label_tracking(paragraph: Any,label: str,indices: dict[Any,int],splits: list[TextSplit],spacing: int) -> bool:
    first=next((r for r in paragraph.findall(W+'r') if r.find(W+'t') is not None and (r.find(W+'t').text or '')),None)
    if first is None or len(first.findall(W+'t'))!=1 or any(n.tag not in {W+'rPr',W+'t'} for n in first):
        return False
    node=first.find(W+'t');value=node.text or ''
    if not value.startswith(label) or _node(first,'rPr').find(W+'vanish') is not None:
        return False
    if len(value)>len(label):
        # Clone only a drawing/field-free literal run. No formatting is dropped.
        prefix=copy.deepcopy(first);prefix.find(W+'t').text=label
        node.text=value[len(label):]
        if node.text[:1].isspace() or node.text[-1:].isspace():
            node.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
        paragraph.insert(list(paragraph).index(first),prefix)
        splits.append(TextSplit(indices[node],value,label,node.text))
        first=prefix
    _set(_node(first,'rPr'),'spacing',val=str(spacing))
    return True


def _note(paragraph: Any,profile: FormattingProfile,*,grouped: bool) -> None:
    format_font(paragraph,profile.note_pt)
    if grouped:
        return  # Keep a measured figure-note-caption group intact.
    ppr=_node(paragraph,'pPr')
    _node(ppr,'spacing').attrib.clear()
    _set(ppr,'spacing',before='0',after='0',line=str(round(profile.body_line*240)),lineRule='auto')
    _set(ppr,'snapToGrid',val='0');_set(ppr,'keepNext',val='0');_set(ppr,'keepLines',val='0')
    _set(ppr,'widowControl',val='1')
    ind=_node(ppr,'ind')
    for key in ('hanging','hangingChars','firstLineChars'):
        ind.attrib.pop(W+key,None)
    _set(ppr,'ind',left='0',start='0',firstLine=str(round(profile.indent_mm*1440/25.4)),right='0',end='0')


def _figure_group(blocks: list[Any],index: int) -> bool:
    before=blocks[max(0,index-7):index]
    after=blocks[index+1:index+8]
    return any(p.xpath('.//w:drawing | .//w:pict | .//w:object',namespaces=NS) for p in before) and any(
        p.tag==W+'p' and re.match(r'^Рисунок\s+',_text(p)) for p in after)


def _toc(document: Any,body: Any,styles: Any,roles: dict[str,str],profile: FormattingProfile,warnings: list[str]) -> int:
    count=0
    bookmarks=set(document.xpath('.//w:bookmarkStart/@w:name',namespaces=NS))
    for block in body.findall(W+'sdt'):
        galleries=block.xpath('./w:sdtPr/w:docPartObj/w:docPartGallery/@w:val',namespaces=NS)
        if galleries not in (['Table of Contents'],['Оглавление']):
            continue
        width,_=_section_bounds(body,block)
        reserve=round(profile.toc_page_reserve_mm*1440/25.4)
        for paragraph in block.findall('w:sdtContent/w:p',NS):
            style=paragraph.find('w:pPr/w:pStyle',NS)
            role=roles.get(style.get(W+'val',''),'') if style is not None else ''
            if role not in {'toc1','toc2'}:
                continue
            anchors=paragraph.xpath('./w:hyperlink/@w:anchor',namespaces=NS)
            events=paragraph.xpath('./w:r/w:t | ./w:r/w:tab | ./w:hyperlink/w:r/w:t | ./w:hyperlink/w:r/w:tab',namespaces=NS)
            stops=[i for i,n in enumerate(events) if n.tag==W+'tab']
            if len(anchors)!=1 or anchors[0] not in bookmarks or len(stops) not in {1,2}:
                warnings.append('Неоднозначная строка содержания сохранена: '+_text(paragraph)[:80]);continue
            number=''.join(n.text or '' for n in events[:stops[0]])
            page=''.join(n.text or '' for n in events[stops[-1]+1:])
            numbered=len(stops)==2 and bool(re.fullmatch(r'\d+(?:\.\d+)*',number.strip()))
            if not page.isdecimal() or (len(stops)==2 and not numbered):
                warnings.append('Неопознанные номер/табуляции содержания сохранены: '+_text(paragraph)[:80]);continue
            level=1 if role=='toc2' else 0
            marker=round(level*profile.toc_indent_mm*1440/25.4)
            label=round(profile.indent_mm*1440/25.4) if numbered else 0
            if width-reserve-marker-label<1500:
                warnings.append('Слишком узкая область содержания; требуется проверка.');continue
            ppr=_node(paragraph,'pPr');ind=_node(ppr,'ind');ind.attrib.clear()
            _set(ppr,'ind',left=str(marker+label),start=str(marker+label),right=str(reserve),end=str(reserve),hanging=str(label))
            positions={t.get(W+'pos') for t in ppr.findall('w:tabs/w:tab',NS)}
            key=style.get(W+'val') if style is not None else None
            seen: set[str]=set()
            while key and key not in seen and styles is not None:
                seen.add(key)
                source=next((s for s in styles.findall(W+'style') if s.get(W+'styleId')==key),None)
                if source is None:break
                positions.update(t.get(W+'pos') for t in source.findall('w:pPr/w:tabs/w:tab',NS))
                base=source.find(W+'basedOn');key=base.get(W+'val') if base is not None else None
            tabs=_node(ppr,'tabs');tabs[:]=[]
            for position in sorted(p for p in positions if p and p.lstrip('-').isdigit() and int(p) not in {marker+label,width}):
                clear=ET.SubElement(tabs,W+'tab');clear.set(W+'val','clear');clear.set(W+'pos',position)
            if numbered:
                tab=ET.SubElement(tabs,W+'tab');tab.set(W+'val','left');tab.set(W+'pos',str(marker+label))
            tab=ET.SubElement(tabs,W+'tab');tab.set(W+'val','right');tab.set(W+'pos',str(width));tab.set(W+'leader','dot')
            tabs[:]=sorted(tabs,key=lambda t:int(t.get(W+'pos')))
            _node(ppr,'spacing').attrib.clear()
            _set(ppr,'spacing',before='0',after='0',line=str(round(profile.body_line*240)),lineRule='auto')
            _set(ppr,'keepNext',val='0');_set(ppr,'keepLines',val='1');_set(ppr,'snapToGrid',val='0')
            _set(ppr,'jc',val='left')
            for run in paragraph.xpath('./w:r[w:t] | ./w:hyperlink/w:r[w:t]',namespaces=NS):
                rpr=_node(run,'rPr');_set(rpr,'sz',val=str(profile.toc_font_pt*2));_set(rpr,'szCs',val=str(profile.toc_font_pt*2))
            count+=1
        position=list(body).index(block)
        previous=None
        for candidate in reversed(list(body)[max(0,position-5):position]):
            if candidate.tag!=W+'p':break
            if _text(candidate) in {'','Лист'}:continue
            previous=candidate;break
        if previous is not None and previous.tag==W+'p' and _text(previous)=='Содержание' and _plain(previous):
            format_font(previous,profile.toc_font_pt,bold=True)
            pr=_node(previous,'pPr');_set(pr,'jc',val='center');_set(pr,'keepNext',val='1');_set(pr,'pageBreakBefore',val='1')
            _node(pr,'ind').attrib.clear();_set(pr,'ind',firstLine='0',left='0',right='0')
    return count


def normalize_structures(document: Any,styles: Any,numbering: Any,roles: dict[str,str],profile: FormattingProfile) -> StructureReport:
    body=document.find(W+'body')
    if body is None:
        return StructureReport(0,0,0,0,(),())
    indices={n:i for i,n in enumerate(n for n in document.iter() if n.tag in TEXT_TAGS)}
    warnings: list[str]=[];splits: list[TextSplit]=[]
    notes=examples=appendices=table_labels=0
    in_text=False;note_counter: str | None=None;example_counter=False
    blocks=list(body)
    for index,paragraph in enumerate(blocks):
        if paragraph.tag!=W+'p':
            note_counter=None;continue
        text=_text(paragraph)
        style=paragraph.find('w:pPr/w:pStyle',NS)
        role=roles.get(style.get(W+'val',''),'normal') if style is not None else 'normal'
        if role in {'heading1','заголовок1'} or text.startswith('Настоящие технические условия'):
            in_text=True
        if not in_text or not text:
            note_counter=None;continue
        if not _plain(paragraph):
            note_counter=None;continue
        # Only an actual adjacent table caption, never a prose reference.
        if (re.fullmatch(r'Таблица\s+[А-ЯA-Z]?\.?\d+(?:\.\d+)*(?:\s*[—–-]\s*.+)?',text)
                and index+1<len(blocks) and blocks[index+1].tag==W+'tbl'):
            if _label_tracking(paragraph,'Таблица',indices,splits,20):
                table_labels+=1
            else:
                warnings.append('Разрядка метки таблицы требует проверки: '+text[:80])
        # A strict three-line existing appendix heading, not a text mention.
        events=paragraph.xpath('./w:r/w:t | ./w:r/w:br | ./w:r/w:cr',namespaces=NS)
        lines=['']
        for node in events:
            if node.tag==W+'t':lines[-1]+=node.text or ''
            elif node.get(W+'type','textWrapping')=='textWrapping':lines.append('')
        if (len(lines)==3 and re.fullmatch(r'Приложение\s+[А-ЯA-Z0-9]+',lines[0].strip())
                and lines[1].strip() in {'(обязательное)','(рекомендуемое)','(справочное)'} and lines[2].strip()):
            format_font(paragraph,profile.subheading_pt,bold=True)
            pr=_node(paragraph,'pPr');_set(pr,'jc',val='center');_set(pr,'pageBreakBefore',val='1')
            _set(pr,'keepNext',val='1');_set(pr,'keepLines',val='1')
            _node(pr,'ind').attrib.clear();_set(pr,'ind',firstLine='0',left='0',start='0',right='0',end='0')
            appendices+=1
        match=LABEL.match(text)
        if match is not None:
            tail=text[len(match[1]):].strip()
            if match[1] in {'Примечания','Примеры'}:
                if tail not in {'',':'}:match=None
            elif tail and tail[0] not in ':—–-':
                if match[1]!='Пример' or not re.match(r'^\d+\s*[—–:-]',tail):match=None
        level=_level(_chain(paragraph,styles),numbering)
        if match and level is None and role in {'normal','bodytext'}:
            label=match[1];example=label.startswith('Пример')
            grouped=_figure_group(blocks,index)
            _note(paragraph,profile,grouped=grouped)
            if example:format_font(paragraph,profile.note_pt,example=True);examples+=1
            else:notes+=1
            if not example and not _label_tracking(paragraph,label,indices,splits,profile.note_label_spacing_pt*20):
                warnings.append('Разрядка метки примечания требует проверки из-за структуры фрагментов.')
            if label=='Примечание' and re.match(r'^Примечание\s*:',text):
                warnings.append('После «Примечание» сохранено двоеточие: проверьте тире по 6.12.3; пунктуация не переписывалась.')
            note_counter=None
            if label in {'Примечания','Примеры'} and len(text)<=len(label)+1 and index+1<len(blocks):
                following=blocks[index+1]
                next_level=_level(_chain(following,styles),numbering) if following.tag==W+'p' else None
                if next_level is not None:
                    fmt=next_level[2].find(W+'numFmt');pattern=next_level[2].find(W+'lvlText')
                    if (next_level[1]==0 and fmt is not None and fmt.get(W+'val')=='decimal'
                            and pattern is not None and pattern.get(W+'val') in {'%1.','%1)'}):
                        note_counter=next_level[0];example_counter=example
                        _set(_node(paragraph,'pPr'),'keepNext',val='1')
                        _set(_node(paragraph,'pPr'),'keepLines',val='1')
        elif note_counter and level is not None and level[0]==note_counter:
            _note(paragraph,profile,grouped=_figure_group(blocks,index))
            if example_counter:format_font(paragraph,profile.note_pt,example=True);examples+=1
            else:notes+=1
        else:
            note_counter=None
    toc=_toc(document,body,styles,roles,profile,warnings)
    return StructureReport(notes,examples,toc,appendices,tuple(splits),tuple(dict.fromkeys(warnings)),table_labels)
