"""Render the maintained Markdown manual into an editable, navigable DOCX."""
from __future__ import annotations
import re
from pathlib import Path
from docx import Document
from docx.shared import Mm,Pt,RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'docs/user-guide-ru.md'
OUTPUT=ROOT/'docs/BUTUZIK_AI_User_Guide_RU.docx'


def inline(paragraph, text: str) -> None:
    for part in re.split(r'(\*\*[^*]+\*\*)',text):
        r=paragraph.add_run(part[2:-2] if part.startswith('**') else part)
        if part.startswith('**'):r.bold=True


def main() -> None:
    doc=Document();section=doc.sections[0]
    section.page_width=Mm(210);section.page_height=Mm(297)
    section.top_margin=Mm(20);section.bottom_margin=Mm(18)
    section.left_margin=Mm(23);section.right_margin=Mm(18)
    for name in ('Normal','Title','Subtitle','Heading 1','Heading 2','Heading 3'):
        s=doc.styles[name];s.font.name='Liberation Sans';s.font.color.rgb=RGBColor(0,0,0)
        s.paragraph_format.space_after=Pt(6)
        s.paragraph_format.line_spacing=1.15
        fonts=s.element.get_or_add_rPr().find(qn('w:rFonts'))
        if fonts is not None:
            for key in list(fonts.attrib):
                if 'theme' in key.lower():del fonts.attrib[key]
            for attr in ('ascii','hAnsi','eastAsia','cs'):fonts.set(qn('w:'+attr),'Liberation Sans')
    # Strip the base template's decorative title rule and inherited borders.
    for style in doc.styles:
        for border in list(style.element.iter(qn('w:pBdr'))):border.getparent().remove(border)
    doc.styles['Normal'].font.size=Pt(11)
    doc.styles['Title'].font.size=Pt(26)
    doc.styles['Heading 1'].font.size=Pt(17)
    doc.styles['Heading 1'].paragraph_format.space_before=Pt(16)
    doc.styles['Heading 2'].font.size=Pt(13)
    doc.core_properties.title='Руководство пользователя BUTUZIK AI'
    doc.core_properties.subject='Windows x64 — работа пользователя и подготовка администратором'
    doc.core_properties.author='BUTUZIK.AI'
    doc.core_properties.comments=''
    foot=section.footer.paragraphs[0];foot.alignment=2
    foot.add_run('BUTUZIK.AI  •  ')
    field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');foot._p.append(field)
    for run in foot.runs:run.font.size=Pt(9)
    lines=SOURCE.read_text(encoding='utf-8').splitlines();i=0;code=False
    while i<len(lines):
        line=lines[i];i+=1
        if line.startswith('```'):code=not code;continue
        if code:
            p=doc.add_paragraph();p.paragraph_format.space_after=Pt(1);p.paragraph_format.line_spacing=1
            p.paragraph_format.left_indent=Mm(2)
            run=p.add_run(line or ' ');run.font.name='Liberation Mono';run.font.size=Pt(8)
            continue
        if not line.strip():continue
        if line.startswith('|'):
            rows=[line]
            while i<len(lines) and lines[i].startswith('|'):rows.append(lines[i]);i+=1
            parsed=[[c.strip() for c in row.strip('|').split('|')] for row in rows]
            parsed=[r for r in parsed if not all(re.fullmatch(r':?-+:?',c.replace(' ','')) for c in r)]
            table=doc.add_table(rows=0,cols=len(parsed[0]));table.autofit=False
            for index,values in enumerate(parsed):
                cells=table.add_row().cells
                for cell,value in zip(cells,values):
                    cell.vertical_alignment=1;p=cell.paragraphs[0];inline(p,value)
                    p.paragraph_format.space_after=Pt(4);p.paragraph_format.space_before=Pt(4)
                    p.paragraph_format.line_spacing=1.05
                    for run in p.runs:run.font.size=Pt(9);run.bold=index==0
                if index==0:
                    pr=table.rows[-1]._tr.get_or_add_trPr();pr.append(OxmlElement('w:tblHeader'))
                    for cell in cells:
                        sh=OxmlElement('w:shd');sh.set(qn('w:fill'),'E8EDF2');cell._tc.get_or_add_tcPr().append(sh)
            pr=table._tbl.tblPr;borders=OxmlElement('w:tblBorders')
            for side in ('top','left','bottom','right','insideH','insideV'):
                n=OxmlElement('w:'+side);n.set(qn('w:val'),'single');n.set(qn('w:sz'),'4');n.set(qn('w:color'),'D9D9D9');borders.append(n)
            pr.append(borders);doc.add_paragraph();continue
        if line.startswith('# '):
            doc.add_paragraph(line[2:],'Title')
            doc.add_paragraph('Windows x64\nПользователю и администратору\n20 ноября 2026 года','Subtitle')
        elif line.startswith('## '):
            p=doc.add_paragraph(line[3:],'Heading 1')
            # Long handbook: major role transitions start clean pages.
            if re.match(r'(?:1 |19 |21 |24 )',line[3:]):p.paragraph_format.page_break_before=True
        else:
            p=doc.add_paragraph();inline(p,line)
    settings=doc.settings.element;update=OxmlElement('w:updateFields');update.set(qn('w:val'),'true');settings.append(update)
    doc.save(OUTPUT)
    print(OUTPUT)


if __name__=='__main__':main()
