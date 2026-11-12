"""Conservative, deterministic formatting of existing Word structure.

Only called on disposable copies. This profile preserves page furniture,
table values, numbering, fields and opaque objects. It never rewrites technical prose
or certifies full GOST compliance. Rendering/review is mandatory before publish.
"""
from __future__ import annotations

from dataclasses import dataclass
import copy
import hashlib
from pathlib import Path
from zipfile import ZipFile
from typing import Any

from lxml import etree as ET  # type: ignore[import-untyped]

from document_inspection import inspect_docx
from document_elements import normalize_elements
from standard_profiles import load_profile

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
NS = {'w': W[1:-1]}


@dataclass(frozen=True)
class FormatReport:
    profile: str
    changes: tuple[str, ...]
    warnings: tuple[str, ...]
    preserved_parts: int
    body_text_preserved: bool
    full_conformance_checked: bool = False


def _element(parent: Any, tag: str) -> Any:
    found = parent.find(W + tag)
    if found is None:
        found = ET.SubElement(parent, W + tag)
        if tag in {'pPr', 'rPr'}:
            parent.remove(found)
            parent.insert(0, found)
    return found


def _prop(parent: Any, tag: str, **attrs: str) -> None:
    child = _element(parent, tag)
    for name, value in attrs.items():
        child.set(W + name, value)


def _texts(root: Any) -> list[tuple[str, str]]:
    return [(node.tag, node.text or '') for node in root.iter()
            if node.tag in {W + 't', W + 'instrText', W + 'delText'}]


def format_docx(source: Path, target: Path) -> FormatReport:
    profile = load_profile()
    if source.resolve() == target.resolve() or target.exists():
        raise ValueError('Оформление выполняется только в новую копию')
    evidence = inspect_docx(source)
    if evidence.has_macros or any(p.name.startswith('_xmlsignatures/') for p in evidence.parts):
        raise ValueError('Подписанный документ или макросы требуют отдельной обработки; оригинал сохранён')
    parser = ET.XMLParser(resolve_entities=False, no_network=True)
    with ZipFile(source) as package:
        document_raw = package.read('word/document.xml')
        document = ET.fromstring(document_raw, parser)
        styles = ET.fromstring(package.read('word/styles.xml'), parser) if 'word/styles.xml' in package.namelist() else None
        roles: dict[str, str] = {}
        if styles is not None:
            for style in styles.findall(W + 'style'):
                name = style.find(W + 'name')
                if name is not None:
                    roles[style.get(W + 'styleId', '')] = name.get(W + 'val', '').lower().replace(' ', '')
        before = _texts(document)
        headings = body_count = 0
        in_main = False
        appendix = False
        for paragraph in document.findall('w:body/w:p', NS):
            # Do not treat contents, title blocks or numbered body requirements
            # using Heading 3/4 as section headings.
            if not paragraph.xpath('.//w:t', namespaces=NS):
                continue
            plain = ''.join(paragraph.xpath('.//w:t/text()', namespaces=NS)).strip()
            if plain.startswith('Приложение '):
                appendix = True
            if appendix:
                continue
            ppr = paragraph.find(W + 'pPr')
            style = ppr.find(W + 'pStyle') if ppr is not None else None
            role = roles.get(style.get(W + 'val', ''), '') if style is not None else 'normal'
            if role in {'heading1', 'заголовок1'}:
                in_main = True
            if not in_main:
                continue
            if paragraph.xpath('.//w:drawing | .//w:pict | .//w:object | .//w:fldChar', namespaces=NS):
                continue
            ppr = _element(paragraph, 'pPr')
            if role in {'heading1', 'heading2', 'заголовок1', 'заголовок2'}:
                headings += 1
                _prop(ppr, 'keepNext', val='1')
                _prop(ppr, 'suppressAutoHyphens', val='1')
                _prop(ppr, 'spacing', before=str(profile.heading_gap_pt * 20),
                      after=str(profile.heading_gap_pt * 20),
                      line=str(round(profile.body_line * 240)), lineRule='auto')
                if role in {'heading1', 'заголовок1'}:
                    _prop(ppr, 'pageBreakBefore', val='1')
                for run in paragraph.findall(W + 'r'):
                    if run.find(W + 't') is not None:
                        rpr = run.find(W + 'rPr')
                        if rpr is None:
                            rpr = ET.Element(W + 'rPr'); run.insert(0, rpr)
                        _prop(rpr, 'b', val='1')
                        _prop(rpr, 'u', val='none')
                        size = str(2 * (profile.heading_pt if role in {'heading1', 'заголовок1'} else profile.subheading_pt))
                        _prop(rpr, 'sz', val=size)
                        _prop(rpr, 'szCs', val=size)
            elif role in {'normal', 'bodytext', 'heading3', 'heading4', 'заголовок3', 'заголовок4'}:
                body_count += 1
                _prop(ppr, 'spacing', line=str(round(profile.body_line * 240)), lineRule='auto')
                # Existing numbering/tab geometry stays intact. Only prose
                # paragraphs with a known role receive a uniform first-line indent.
                if role in {'normal', 'bodytext'} and ppr.find(W + 'numPr') is None:
                    alignment = ppr.find(W + 'jc')
                    if alignment is None or alignment.get(W + 'val') in {'both', 'left'}:
                        indent = _element(ppr, 'ind')
                        indent.attrib.pop(W + 'hanging', None)
                        indent.set(W + 'firstLine', str(round(profile.indent_mm * 1440 / 25.4)))
            order = ('pStyle', 'keepNext', 'keepLines', 'pageBreakBefore', 'framePr',
                     'widowControl', 'numPr', 'suppressLineNumbers', 'pBdr', 'shd',
                     'tabs', 'suppressAutoHyphens', 'kinsoku', 'wordWrap', 'overflowPunct',
                     'topLinePunct', 'autoSpaceDE', 'autoSpaceDN', 'bidi', 'adjustRightInd',
                     'snapToGrid', 'spacing', 'ind', 'contextualSpacing', 'mirrorIndents',
                     'suppressOverlap', 'jc', 'textDirection', 'textAlignment', 'textboxTightWrap',
                     'outlineLvl', 'divId', 'cnfStyle', 'rPr', 'sectPr', 'pPrChange')
            rank = {W + tag: n for n, tag in enumerate(order)}
            ppr[:] = sorted(ppr, key=lambda child: rank.get(child.tag, len(order)))
        # Continuous sections inherit the normal page furniture. A separate first
        # page here can repeat the first numbered sheet's literal stamp/page.
        for section in document.findall('.//w:sectPr', NS):
            kind = section.find(W + 'type')
            first = section.find(W + 'titlePg')
            if kind is not None and kind.get(W + 'val') == 'continuous' and first is not None:
                section.remove(first)
        if not headings:
            raise ValueError('Не найдены размеченные разделы. Нужна проверка структуры; автоматическое угадывание отключено.')
        elements = normalize_elements(document, profile.table_pt, profile.table_header_pt)
        if _texts(document) != before:
            raise ValueError('Нарушена сохранность текста; результат не публикуется')
        updates = {'word/document.xml': ET.tostring(document, xml_declaration=True, encoding='UTF-8', standalone=True)}
        from document_layout import normalize_stamps
        rotated = dates = page_fields = 0
        for name in package.namelist():
            if name.startswith(('word/header', 'word/footer')) and name.endswith('.xml'):
                part = ET.fromstring(package.read(name), parser)
                counts = normalize_stamps(part)
                rotated += counts[0]; dates += counts[1]; page_fields += counts[2]
                if any(counts):
                    updates[name] = ET.tostring(part, xml_declaration=True, encoding='UTF-8', standalone=True)
        if 'word/settings.xml' in package.namelist():
            settings = ET.fromstring(package.read('word/settings.xml'), parser)
            _prop(settings, 'updateFields', val='true')
            updates['word/settings.xml'] = ET.tostring(settings, xml_declaration=True, encoding='UTF-8', standalone=True)
        with ZipFile(target, 'w') as result:
            for entry in package.infolist():
                result.writestr(copy.copy(entry), updates.get(entry.filename, package.read(entry.filename)))
        with ZipFile(target) as result:
            for entry in package.infolist():
                if entry.filename not in updates and package.read(entry.filename) != result.read(entry.filename):
                    target.unlink(missing_ok=True)
                    raise ValueError('Изменилась защищённая часть документа')
    if hashlib.sha256(source.read_bytes()).hexdigest() != evidence.source_sha256:
        target.unlink(missing_ok=True)
        raise ValueError('Исходная копия изменилась во время обработки')
    warnings = [
        'Перед сохранением проверьте страницы: рамки, штампы, переносы таблиц и читаемость схем.',
        'Применены выбранные правила профиля; полная проверка всех требований ГОСТ не выполнялась.',
        'Размеры рамок и граф, подписи, даты и техническое содержание сохранены; служебные поля страниц обновляются отдельно.',
    ]
    if evidence.field_kinds:
        warnings.append('Содержание и поля страниц сверяются с предпросмотром; при изменениях в Word обновите поля повторно.')
    if evidence.embedded_objects:
        warnings.append('Встроенные объекты сохранены без запуска; их отображение требует проверки.')
    if evidence.external_relationships:
        warnings.append('Внешние ссылки сохранены без загрузки и обновления.')
    warnings.extend(elements.warnings)
    return FormatReport(profile.title, (
        f'Оформлены заголовки разделов и подразделов: {headings}.',
        f'Межстрочный интервал {profile.body_line:g} применён к основному тексту: {body_count} абзацев.',
        f'Для обычных абзацев применён отступ {profile.indent_mm:g} мм; нумерация и специальные блоки сохранены.',
        f'Оформлены таблицы с подписями: {elements.tables}. Сохранены значения и объединения ячеек; настроены шапки и переносы.',
        f'Размещены существующие рисунки: {elements.figures}. Масштаб пропорциональный; подписи и пояснения связаны с изображением.',
        ('Исправлено отображение вертикальных подписей, дат и номеров в штампах; число листов связано с документом.'
         if rotated or dates or page_fields else 'Штампы сохранены; их оформление проверяется на страницах предпросмотра.'),
        'Текст, таблицы документа, изображения и вложенные объекты проверены на сохранность.',
    ), tuple(warnings), len(evidence.parts) - len(updates), True)
