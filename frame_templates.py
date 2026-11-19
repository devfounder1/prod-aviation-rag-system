"""Opt-in editable A4 forms 2/2a from the pinned supplied R 2.104-2023.

This is a separate, explicit template operation, never part of the default
formatting recipe. Rebind only reviewed header/footer parts in exact input
bytes; retain the old parts, relationships, media and body without modification.
The forms do not invent signatures, approval, organizational or version data.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
import re
from typing import Any, Literal
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import etree as E  # type: ignore[import-untyped]

from document_inspection import W, _parse
from tu_validation import _read

SOURCE_SHA256 = '2fdb4e0c5dac26f5824dbdb8aafd0f20cacc1a0490222e3ee6d016c0b9df2094'
NS = {
    'w': W[1:-1], 'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
    'wps': 'http://schemas.microsoft.com/office/word/2010/wordprocessingShape',
    'wpg': 'http://schemas.microsoft.com/office/word/2010/wordprocessingGroup',
    'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture',
}
REL = '{http://schemas.openxmlformats.org/package/2006/relationships}'
CT = '{http://schemas.openxmlformats.org/package/2006/content-types}'
EMU = 36000
Form = Literal['2', '2a', 'title']


def _node(parent: Any, tag: str, **attrs: str) -> Any:
    prefix, local = tag.split(':')
    child = E.SubElement(parent, '{'+NS[prefix]+'}'+local)
    for key, value in attrs.items():
        if ':' in key:
            p, k = key.split(':'); key = '{'+NS[p]+'}'+k
        child.set(key, value)
    return child


def _mm(value: float) -> str:
    return str(round(value*EMU))


@dataclass(frozen=True)
class ApprovalRow:
    role: str
    name: str = ''
    date: str = ''


@dataclass(frozen=True)
class StampValues:
    designation: str = ''
    title: str = ''
    organization: str = ''
    primary_application: str = ''
    reference_number: str = ''
    version: str = ''
    letter: str = ''
    format_label: str = 'А4'
    approvals: tuple[ApprovalRow, ...] = ()


@dataclass(frozen=True)
class SignatureCopy:
    """An existing picture, its reviewed target approval row and physical size.

    XML is a pic:pic copied from the source header; its original r:embed ID and
    relationship part are retained. No image generation or host file lookup.
    """
    picture_xml: bytes
    row: int
    width_mm: float
    height_mm: float


class _Drawing:
    def __init__(self, identifier: str) -> None:
        self.root = E.Element(W+'hdr', nsmap=NS)
        p = _node(self.root, 'w:p'); pp = _node(p, 'w:pPr')
        _node(pp, 'w:spacing', **{'w:before':'0','w:after':'0','w:line':'20','w:lineRule':'exact'})
        drawing = _node(_node(p, 'w:r'), 'w:drawing')
        anchor = _node(drawing, 'wp:anchor', distT='0', distB='0', distL='0', distR='0',
                       simplePos='0', relativeHeight='0', behindDoc='1', locked='0', layoutInCell='0', allowOverlap='1')
        _node(anchor, 'wp:simplePos', x='0', y='0')
        for axis in ('H','V'):
            _node(_node(anchor, 'wp:position'+axis, relativeFrom='page'), 'wp:posOffset').text = '0'
        _node(anchor, 'wp:extent', cx=_mm(210), cy=_mm(297))
        _node(anchor, 'wp:effectExtent', l='0', t='0', r='0', b='0')
        _node(anchor, 'wp:wrapNone'); _node(anchor, 'wp:docPr', id=identifier, name='BUTUZ reviewed A4 frame')
        data = _node(_node(anchor, 'a:graphic'), 'a:graphicData', uri=NS['wpg'])
        self.group = _node(data, 'wpg:wgp'); _node(self.group, 'wpg:cNvGrpSpPr')
        transform = _node(_node(self.group, 'wpg:grpSpPr'), 'a:xfrm')
        for tag, attrs in (('off',{'x':'0','y':'0'}), ('ext',{'cx':_mm(210),'cy':_mm(297)}),
                           ('chOff',{'x':'0','y':'0'}), ('chExt',{'cx':_mm(210),'cy':_mm(297)})):
            _node(transform, 'a:'+tag, **attrs)
        # Keep the group's logical origin and bounds explicit even when a
        # renderer normalizes child bounds (Word compatibility modes differ).
        self.shape(0,0,210,297)

    def shape(self, x: float, y: float, width: float, height: float,
              geometry: str = 'rect', stroke: float = 0) -> Any:
        shape = _node(self.group, 'wps:wsp'); _node(shape, 'wps:cNvSpPr', txBox='1')
        properties = _node(shape, 'wps:spPr'); transform = _node(properties, 'a:xfrm')
        _node(transform, 'a:off', x=_mm(x), y=_mm(y)); _node(transform, 'a:ext', cx=_mm(width), cy=_mm(height))
        _node(_node(properties, 'a:prstGeom', prst=geometry), 'a:avLst')
        _node(properties, 'a:noFill')
        line = _node(properties, 'a:ln', w=_mm(stroke))
        if stroke:
            _node(_node(line, 'a:solidFill'), 'a:srgbClr', val='000000')
            _node(line, 'a:prstDash', val='solid')
        else:
            _node(line, 'a:noFill')
        return shape

    def line(self, x1: float, y1: float, x2: float, y2: float, thick: bool = False) -> None:
        self.shape(x1,y1,x2-x1,y2-y1,'line', .5 if thick else .25)

    def text(self, x: float, y: float, width: float, height: float, text: str = '',
             size: float = 7, field: str = '', vertical: bool = False, align: str = 'center') -> None:
        shape = self.shape(x,y,width,height)
        content = _node(_node(shape, 'wps:txbx'), 'w:txbxContent')
        # Native cell direction works in both Word and the isolated renderer.
        # A paragraph's textDirection is not a textbox rotation instruction.
        table = _node(content, 'w:tbl'); tp = _node(table, 'w:tblPr')
        twips = str(round(width*1440/25.4))
        _node(tp,'w:tblW',**{'w:w':twips,'w:type':'dxa'})
        _node(tp,'w:tblInd',**{'w:w':'0','w:type':'dxa'})
        borders = _node(tp,'w:tblBorders')
        for edge in ('top','left','bottom','right','insideH','insideV'):
            _node(borders,'w:'+edge,**{'w:val':'nil'})
        _node(tp,'w:tblLayout',**{'w:type':'fixed'})
        margins = _node(tp,'w:tblCellMar')
        for edge in ('top','left','bottom','right'):
            _node(margins,'w:'+edge,**{'w:w':'0','w:type':'dxa'})
        _node(_node(table,'w:tblGrid'),'w:gridCol',**{'w:w':twips})
        row = _node(table,'w:tr')
        _node(_node(row,'w:trPr'),'w:trHeight',**{'w:val':str(round(height*1440/25.4)-8),'w:hRule':'exact'})
        cell = _node(row,'w:tc'); cp = _node(cell,'w:tcPr')
        _node(cp,'w:tcW',**{'w:w':twips,'w:type':'dxa'})
        if vertical: _node(cp,'w:textDirection',**{'w:val':'btLr'})
        _node(cp,'w:vAlign',**{'w:val':'center'})
        for line in text.split('\n'):
            p = _node(cell, 'w:p'); pp = _node(p, 'w:pPr')
            _node(pp, 'w:spacing', **{'w:before':'0','w:after':'0','w:line':'240','w:lineRule':'auto'})
            _node(pp, 'w:ind', **{'w:left':'0','w:right':'0','w:firstLine':'0'})
            _node(pp, 'w:jc', **{'w:val':align})
            self.font(pp,size)
            if field:
                for kind in ('begin','instruction','separate','value','end'):
                    run = _node(p, 'w:r'); self.font(run,size)
                    if kind == 'instruction': _node(run, 'w:instrText').text = ' '+field+' '
                    elif kind == 'value': _node(run, 'w:t').text = line or '1'
                    else: _node(run, 'w:fldChar', **{'w:fldCharType':kind})
            else:
                run = _node(p, 'w:r'); self.font(run,size); _node(run, 'w:t').text = line
        body = _node(shape, 'wps:bodyPr', lIns='0', rIns='0', tIns='0', bIns='0', anchor='t')
        _node(body, 'a:noAutofit')

    @staticmethod
    def font(run: Any, size: float) -> None:
        props = _node(run, 'w:rPr')
        _node(props, 'w:rFonts', **{'w:ascii':'Liberation Sans','w:hAnsi':'Liberation Sans','w:cs':'Liberation Sans'})
        _node(props, 'w:sz', **{'w:val':str(round(size*2))})
        _node(props, 'w:szCs', **{'w:val':str(round(size*2))})
        _node(props, 'w:color', **{'w:val':'000000'})


def make_header(form: Form, values: StampValues = StampValues(),
                signatures: tuple[SignatureCopy, ...] = ()) -> bytes:
    """Editable vectors at physical page coordinates; not a conformity verdict.

    B.2/B.3, supplied PDF pp.16–17: 185x40 / 185x15; 20/5/5/5 frame.
    Blank conditional fields are left blank. No graphical-only column 26 in TU.
    """
    if form not in {'2','2a','title'}: raise ValueError('Неизвестная форма')
    if len(values.approvals)>5 or (signatures and form!='2'): raise ValueError('Неподдерживаемые строки подписей')
    if any(len(s)>300 or any(ord(c)<32 and c!='\n' for c in s) for s in (
        values.designation,values.title,values.organization,values.primary_application,values.reference_number,
        values.version,values.letter,values.format_label,*(v for row in values.approvals for v in (row.role,row.name,row.date)))):
        raise ValueError('Слишком длинные или недопустимые реквизиты')
    d = _Drawing({'2':'91000','2a':'91001','title':'91002'}[form])
    d.shape(20,5,185,287,stroke=.5)
    # Additional registration columns 19–23: bottom-up 25/35/25/25/35.
    d.shape(8,147,12,145,stroke=.5); d.line(13,147,13,292)
    for y in (182,207,232,267): d.line(8,y,20,y)
    for y,h,label in ((147,35,'Подп. и дата'),(182,25,'Инв. № дубл.'),(207,25,'Взам. инв. №'),
                      (232,35,'Подп. и дата'),(267,25,'Инв. № подл.')):
        d.text(8,y,5,h,label,7,vertical=True)
    if form=='title': return bytes(E.tostring(d.root,xml_declaration=True,encoding='UTF-8',standalone=True))
    y = 252 if form=='2' else 277
    d.line(20,y,205,y,True)
    if form=='2':
        d.shape(8,5,12,120,stroke=.5); d.line(13,5,13,125); d.line(8,65,20,65)
        for top,label,value in ((5,'Перв. примен.',values.primary_application),(65,'Справ. №',values.reference_number)):
            d.text(8,top,5,60,label,7,vertical=True); d.text(13,top,7,60,value,7,vertical=True)
    # Change registration grid: five widths 7/10/23/15/10 mm.
    for x in (27,37,60,75,85): d.line(x,y,x,292, x==85)
    for top in range(y+5,268 if form=='2' else 292,5): d.line(20,top,85,top)
    for x,w,label in ((20,7,'Изм.'),(27,10,'Лист'),(37,23,'№ докум.'),(60,15,'Подп.'),(75,10,'Дата')):
        d.text(x,262 if form=='2' else 287,w,5,label,6.5)
    if form=='2':
        d.line(85,267,205,267,True); d.line(195,252,195,267); d.line(195,257,205,257)
        d.text(85,252,110,15,values.designation,12)
        d.text(195,252,10,5,'Вер.',6.5); d.text(195,257,10,10,values.version,8)
        for top in (272,277,282,287): d.line(20,top,85,top)
        for index,row in enumerate(values.approvals):
            top=267+5*index
            d.text(20,top,17,5,row.role,6.5,align='left'); d.text(37,top,23,5,row.name,6.5,align='left')
            d.text(75,top,10,5,row.date,5.5)
        d.line(155,267,155,292,True); d.line(155,272,205,272); d.line(155,277,205,277)
        for x in (170,185): d.line(x,267,x,277)
        for x in (160,165): d.line(x,272,x,277)
        for x,w,label in ((155,15,'Лит.'),(170,15,'Лист'),(185,20,'Листов')): d.text(x,267,w,5,label,6.5)
        d.text(155,272,15,5,values.letter,7)
        d.text(170,272,15,5,'2',8,field='PAGE'); d.text(185,272,20,5,'1',8,field='NUMPAGES')
        d.text(85,267,70,25,values.title,11); d.text(155,277,50,15,values.organization,9)
    else:
        d.line(185,277,185,292); d.line(195,277,195,292); d.line(185,282,205,282)
        d.text(85,277,100,15,values.designation,12)
        d.text(185,277,10,5,'Вер.',6.5); d.text(185,282,10,10,values.version,8)
        d.text(195,277,10,5,'Лист',6.5); d.text(195,282,10,10,'1',10,field='PAGE')
    d.text(130,292,35,4,'Копировал',5.5); d.text(175,292,30,4,'Формат '+values.format_label,5.5)
    for sig in signatures:
        if not 0<=sig.row<5 or not 0<sig.width_mm<=15 or not 0<sig.height_mm<=5:
            raise ValueError('Подпись не помещается в согласованную графу')
        _parse(sig.picture_xml)
        pic=E.fromstring(sig.picture_xml,E.XMLParser(resolve_entities=False,no_network=True))
        if pic.tag!='{'+NS['pic']+'}pic' or len(pic.findall('.//{'+NS['a']+'}blip'))!=1:
            raise ValueError('Нужна исходная картинка подписи')
        transform=pic.find('{'+NS['pic']+'}spPr/{'+NS['a']+'}xfrm')
        if transform is None:raise ValueError('Нет геометрии исходной подписи')
        off=transform.find('{'+NS['a']+'}off'); ext=transform.find('{'+NS['a']+'}ext')
        if off is None or ext is None:raise ValueError('Нет геометрии исходной подписи')
        off.set('x',_mm(60+(15-sig.width_mm)/2)); off.set('y',_mm(267+sig.row*5+(5-sig.height_mm)/2))
        ext.set('cx',_mm(sig.width_mm));ext.set('cy',_mm(sig.height_mm));d.group.append(pic)
    return bytes(E.tostring(d.root,xml_declaration=True,encoding='UTF-8',standalone=True))


@dataclass(frozen=True)
class HeaderReplacement:
    source_part: str
    source_sha256: str
    new_xml: bytes


def replace_furniture(raw: bytes, expected_sha256: str,
                      replacements: tuple[HeaderReplacement,...]) -> bytes:
    """An exact-byte plan, new active parts; originals remain byte-identical.

    No automatic template detection or metadata extraction. The caller reviews
    roles/fields and renders the complete new copy before publishing it.
    """
    if hashlib.sha256(raw).hexdigest()!=expected_sha256:raise ValueError('Исходная копия изменилась')
    document,_ = _read(raw)  # bounded ZIP/XML checks before using lxml
    sections=list(document.iter(W+'sectPr'))
    if not sections:raise ValueError('Нет определённого формата страницы')
    for section in sections:
        size=section.find(W+'pgSz')
        if size is None or any(abs(int(size.get(W+key,'0'))*25.4/1440-mm)>.2
                               for key,mm in (('w',210),('h',297))):
            raise ValueError('Шаблон предназначен только для книжного A4')
    if not 1<=len(replacements)<=8 or len({r.source_part for r in replacements})!=len(replacements):
        raise ValueError('Неоднозначный план замены')
    parser=E.XMLParser(resolve_entities=False,no_network=True)
    with ZipFile(BytesIO(raw)) as package:
        names=set(package.namelist())
        if any(n.startswith('_xmlsignatures/') or n.endswith('vbaProject.bin') for n in names):
            raise ValueError('Подпись пакета или макросы требуют отдельной обработки')
        rels=E.fromstring(package.read('word/_rels/document.xml.rels'),parser)
        types=E.fromstring(package.read('[Content_Types].xml'),parser)
        added: dict[str,bytes]={}
        for index,r in enumerate(replacements,9001):
            match=re.fullmatch(r'word/(header|footer)\d+\.xml',r.source_part)
            if not match or r.source_part not in names:raise ValueError('Недопустимый колонтитул')
            if hashlib.sha256(package.read(r.source_part)).hexdigest()!=r.source_sha256:
                raise ValueError('Колонтитул изменился')
            if len(r.new_xml)>1_000_000:raise ValueError('Слишком большой новый колонтитул')
            kind=match[1];_parse(r.new_xml);root=E.fromstring(r.new_xml,parser)
            if root.tag!=W+('hdr' if kind=='header' else 'ftr'):raise ValueError('Неверный тип колонтитула')
            target=f'{kind}{index}.xml';part='word/'+target
            if part in names or part in added:raise ValueError('Имя нового колонтитула занято')
            bound=[n for n in rels if n.get('Target')==r.source_part[5:] and n.get('Type','').endswith('/'+kind)
                   and n.get('TargetMode')!='External']
            if len(bound)!=1:raise ValueError('Неоднозначная привязка колонтитула')
            bound[0].set('Target',target);added[part]=r.new_xml
            old_rel='word/_rels/'+r.source_part[5:]+'.rels'
            references={value for n in root.iter() for key,value in n.attrib.items()
                        if key in {'{'+NS['r']+'}id','{'+NS['r']+'}embed','{'+NS['r']+'}link'}}
            existing_ids=set()
            if old_rel in names:
                existing_ids={n.get('Id') for n in E.fromstring(package.read(old_rel),parser)}
            if not references<=existing_ids:raise ValueError('Новый колонтитул ссылается на отсутствующее вложение')
            if old_rel in names:added['word/_rels/'+target+'.rels']=package.read(old_rel)
            E.SubElement(types,CT+'Override',PartName='/'+part,
                         ContentType=f'application/vnd.openxmlformats-officedocument.wordprocessingml.{kind}+xml')
        changed={'word/_rels/document.xml.rels':E.tostring(rels,xml_declaration=True,encoding='UTF-8',standalone=True),
                 '[Content_Types].xml':E.tostring(types,xml_declaration=True,encoding='UTF-8',standalone=True)}
        out=BytesIO()
        with ZipFile(out,'w',ZIP_DEFLATED) as dest:
            for item in package.infolist():dest.writestr(item,changed.get(item.filename,package.read(item.filename)))
            for name,data in added.items():dest.writestr(name,data)
    result=out.getvalue();_read(result)
    return result


def blank_template() -> bytes:
    """Neutral two-page editable DOCX sample: form 2 followed by form 2a.

    No organization, signatures or private metadata. Page fields remain live.
    The sample is a print template, not a formal electronic design document.
    """
    from docx import Document
    from docx.enum.section import WD_SECTION_START
    from docx.shared import Mm
    document=Document();section=document.sections[0]
    section.page_width=Mm(210);section.page_height=Mm(297)
    section.left_margin=Mm(25);section.right_margin=Mm(8)
    section.top_margin=Mm(15);section.bottom_margin=Mm(55)
    section.header_distance=Mm(0);section.footer_distance=Mm(0)
    section.header.paragraphs[0].text=''
    document.add_paragraph('')
    later=document.add_section(WD_SECTION_START.NEW_PAGE)
    later.header.is_linked_to_previous=False;later.header.paragraphs[0].text='';later.bottom_margin=Mm(30)
    out=BytesIO();document.save(out);raw=out.getvalue()
    values=StampValues(approvals=tuple(ApprovalRow(role) for role in ('Разраб.','Пров.','','Н. контр.','Утв.')))
    forms: tuple[tuple[int,Form],...] = ((1,'2'),(2,'2a'))
    with ZipFile(BytesIO(raw)) as package:
        replacements=tuple(HeaderReplacement(f'word/header{i}.xml',
            hashlib.sha256(package.read(f'word/header{i}.xml')).hexdigest(),make_header(form,values))
            for i,form in forms)
    return replace_furniture(raw,hashlib.sha256(raw).hexdigest(),replacements)
