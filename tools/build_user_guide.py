"""Render the maintained Markdown manual into an editable, navigable DOCX."""
from __future__ import annotations
import re
from pathlib import Path
from docx import Document
from docx.shared import Mm,Pt,RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.text.paragraph import Paragraph

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'docs/launch-guide-ru.md'
OUTPUT=ROOT/'docs/Инструкция для запуска BUTUZIK AI.docx'


def hyperlink(paragraph: Paragraph, label: str, target: str, internal: bool=False) -> None:
    link=OxmlElement('w:hyperlink')
    if internal:link.set(qn('w:anchor'),target)
    else:link.set(qn('r:id'),paragraph.part.relate_to(target,RT.HYPERLINK,is_external=True))
    run=OxmlElement('w:r');pr=OxmlElement('w:rPr')
    color=OxmlElement('w:color');color.set(qn('w:val'),'000000');pr.append(color)
    under=OxmlElement('w:u');under.set(qn('w:val'),'single');pr.append(under)
    size=OxmlElement('w:sz');size.set(qn('w:val'),'20');pr.append(size)
    run.append(pr);t=OxmlElement('w:t');t.text=label;run.append(t);link.append(run);paragraph._p.append(link)


def inline(paragraph: Paragraph, text: str) -> None:
    for part in re.split(r'(\*\*[^*]+\*\*|\[[^\]]+\]\(https?://[^)]+\))',text):
        link=re.fullmatch(r'\[([^\]]+)\]\((https?://[^)]+)\)',part)
        if link:
            hyperlink(paragraph,link[1],link[2]);continue
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
    doc.core_properties.title='Инструкция для запуска BUTUZIK AI'
    doc.core_properties.subject='Пошаговая подготовка Windows x64 и запуск без интернета'
    doc.core_properties.author='BUTUZIK.AI'
    doc.core_properties.comments=''
    foot=section.footer.paragraphs[0];foot.alignment=2
    foot.add_run('BUTUZIK.AI  •  ')
    field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');foot._p.append(field)
    for run in foot.runs:run.font.size=Pt(9)
    lines=SOURCE.read_text(encoding='utf-8').splitlines();i=0;code=False
    headings=[line[3:] for line in lines if line.startswith('## ')]
    heading_index=0;code_paragraphs: list[Paragraph]=[]
    while i<len(lines):
        line=lines[i];i+=1
        if line.startswith('```'):
            code=not code
            if code:
                code_paragraphs=[]
                if doc.paragraphs:doc.paragraphs[-1].paragraph_format.keep_with_next=True
            else:
                for paragraph in code_paragraphs[:-1]:paragraph.paragraph_format.keep_with_next=True
                if code_paragraphs:code_paragraphs[-1].paragraph_format.space_after=Pt(8)
            continue
        if code:
            p=doc.add_paragraph();p.paragraph_format.space_after=Pt(1);p.paragraph_format.line_spacing=1
            p.paragraph_format.left_indent=Mm(2)
            p.paragraph_format.keep_together=True
            run=p.add_run(line or ' ');run.font.name='Liberation Mono';run.font.size=Pt(9)
            code_paragraphs.append(p)
            continue
        if not line.strip():continue
        if line.startswith('|'):
            rows=[line]
            while i<len(lines) and lines[i].startswith('|'):rows.append(lines[i]);i+=1
            parsed=[[c.strip() for c in row.strip('|').split('|')] for row in rows]
            parsed=[r for r in parsed if not all(re.fullmatch(r':?-+:?',c.replace(' ','')) for c in r)]
            table=doc.add_table(rows=0,cols=len(parsed[0]));table.autofit=False
            first=parsed[0][0]
            widths=([43,73,53] if first=='Компонент' else [43,65,61] if first=='Что получить'
                    else [65,104] if len(parsed[0])==2 else [45,80,44] if first=='Проверка' else [62,55,52])
            for col,width in zip(table.columns,widths):col.width=Mm(width)
            for index,values in enumerate(parsed):
                row=table.add_row();cells=row.cells
                row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
                for cell,value in zip(cells,values):
                    cell.vertical_alignment=1;p=cell.paragraphs[0];inline(p,value)
                    p.paragraph_format.space_after=Pt(4);p.paragraph_format.space_before=Pt(4)
                    p.paragraph_format.line_spacing=1.05
                    for run in p.runs:run.font.size=Pt(10);run.bold=index==0
                    margins=OxmlElement('w:tcMar')
                    for side in ('top','left','bottom','right'):
                        margin=OxmlElement('w:'+side);margin.set(qn('w:w'),'85');margin.set(qn('w:type'),'dxa');margins.append(margin)
                    cell._tc.get_or_add_tcPr().append(margins)
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
            doc.add_paragraph('Windows x64\nОт исходного архива до работы без интернета\n20 ноября 2026 года','Subtitle')
        elif line.startswith('## '):
            if heading_index==0:
                doc.add_page_break();doc.add_paragraph('Содержание','Heading 1')
                doc.add_paragraph('В Word удерживайте Ctrl и нажмите название раздела. Можно также открыть область навигации сочетанием Ctrl+F.')
                for number,title in enumerate(headings,1):
                    p=doc.add_paragraph();p.paragraph_format.space_after=Pt(4)
                    hyperlink(p,title,f'section_{number}',internal=True)
            p=doc.add_paragraph(line[3:],'Heading 1')
            heading_index+=1
            start=OxmlElement('w:bookmarkStart');start.set(qn('w:id'),str(heading_index));start.set(qn('w:name'),f'section_{heading_index}')
            end=OxmlElement('w:bookmarkEnd');end.set(qn('w:id'),str(heading_index));p._p.insert(1,start);p._p.append(end)
            if heading_index==1:p.paragraph_format.page_break_before=True
        elif line.startswith('### '):
            doc.add_paragraph(line[4:],'Heading 2')
        else:
            p=doc.add_paragraph();inline(p,line)
    settings=doc.settings.element;update=OxmlElement('w:updateFields');update.set(qn('w:val'),'true');settings.append(update)
    doc.save(OUTPUT)
    print(OUTPUT)


if __name__=='__main__':main()
