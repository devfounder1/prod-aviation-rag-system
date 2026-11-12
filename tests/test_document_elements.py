from __future__ import annotations

import io
import json
from pathlib import Path
import shutil
from zipfile import ZipFile

from docx import Document
from docx.shared import Inches, Pt
from docx.enum.table import WD_ROW_HEIGHT_RULE
from lxml import etree as ET
from PIL import Image
import pytest

from document_elements import normalize_elements
from gost_formatter import format_docx
from standard_profiles import load_profile

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
WP = '{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}'
NS = {'w': W[1:-1], 'wp': WP[1:-1]}


def test_selected_profile_does_not_read_unselected_hundred_sources(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / 'standards'
    shutil.copytree(source, tmp_path / 'standards')
    directory = tmp_path / 'standards'
    for index in range(120):
        (directory / f'unselected_{index}.json').write_text('{invalid: not a selected standard}')
    profile = load_profile(directory)
    assert profile.table_pt == 12
    assert len(profile.selected_files) == 3
    evidence = directory / 'gost_r_2_105_2019.json'
    data = json.loads(evidence.read_text()); data['source']['sha256'] = 'a' * 64
    evidence.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Редакция'):
        load_profile(directory)


@pytest.mark.parametrize('change', ['duplicate', 'missing_rule', 'removed_rule', 'removed_source',
                                  'invalid_setting', 'path_escape'])
def test_profile_rejects_ambiguous_or_unreviewed_selection(tmp_path: Path, change: str) -> None:
    source = Path(__file__).resolve().parents[1] / 'standards'
    shutil.copytree(source, tmp_path / 'standards')
    directory = tmp_path / 'standards'
    recipe = directory / 'profiles/eskd_text.json'
    data = json.loads(recipe.read_text())
    if change == 'duplicate':
        recipe.write_text('{"schema_version":1,"schema_version":2}')
    else:
        if change == 'missing_rule':
            data['sources'][0]['rule_ids'].append('invented-clause')
        elif change == 'removed_rule':
            data['sources'][0]['rule_ids'].remove('figure-caption-position')
        elif change == 'removed_source':
            data['sources'].pop()
        elif change == 'invalid_setting':
            data['project_choices']['table_pt'] = 0
        else:
            data['sources'][0]['file'] = '../outside.json'
        recipe.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_profile(directory)


def test_captioned_table_repeats_merged_header_preserves_values_and_title_forms(tmp_path: Path) -> None:
    doc = Document()
    title_form = doc.add_table(rows=2, cols=2)
    title_form.cell(0, 0).text = 'УТВЕРЖДАЮ'
    untouched = ET.tostring(title_form._tbl)
    doc.add_heading('Requirements', level=1)
    doc.add_paragraph('Данные приведены в таблице 1.')
    doc.add_paragraph('Таблица 1 — Параметры')
    table = doc.add_table(rows=4, cols=3)
    table.cell(0, 0).merge(table.cell(1, 0)).text = 'Наименование'
    table.cell(0, 1).merge(table.cell(0, 2)).text = 'Значение'
    table.cell(1, 1).text = 'Мин.'; table.cell(1, 2).text = 'Макс.'
    table.cell(2, 0).text = 'Ток'; table.cell(2, 1).text = '0,001'; table.cell(2, 2).text = '27,5'
    table.cell(3, 0).text = 'Очень длинное пояснение. ' * 300
    table.rows[2].height = Pt(8); table.rows[2].height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
    for col in table._tbl.findall('w:tblGrid/w:gridCol', NS):
        col.set(W + 'w', '7000')
    table._tbl.find('w:tr', NS).get_or_add_trPr().append(ET.Element(W + 'tblHeader'))
    before_text = table._tbl.xpath('.//w:t/text()')
    before_merges = [ET.tostring(p) for p in table._tbl.xpath('.//w:vMerge | .//w:gridSpan')]
    source, target = tmp_path/'source.docx', tmp_path/'result.docx'
    doc.save(source)
    report = format_docx(source, target)
    result = Document(target)
    formatted = ET.fromstring(ET.tostring(result.tables[1]._tbl))
    assert ET.tostring(result.tables[0]._tbl) == untouched
    assert formatted.xpath('.//w:t/text()', namespaces=NS) == before_text
    assert [ET.tostring(p) for p in formatted.xpath('.//w:vMerge | .//w:gridSpan', namespaces=NS)] == before_merges
    assert [r.find('w:trPr/w:tblHeader', NS).get(W+'val') for r in formatted.findall(W+'tr')] == ['1', '1', '0', '0']
    assert formatted.find('w:tr[3]/w:trPr/w:trHeight', NS).get(W+'hRule') == 'atLeast'
    assert formatted.find('w:tr[4]/w:trPr/w:cantSplit', NS).get(W+'val') == '0'
    assert all(p.get(W+'val') == '0' for p in formatted.findall('w:tr[4]/w:tc/w:p/w:pPr/w:keepLines', NS))
    section = result.sections[0]
    assert sum(int(col.get(W+'w')) for col in formatted.findall('w:tblGrid/w:gridCol', NS)) <= (section.page_width-section.left_margin-section.right_margin) // 635
    assert not any('таблица 1' in warning for warning in report.warnings)


def test_unknown_or_nested_table_is_not_reinterpreted_as_simple_data() -> None:
    doc = Document(); doc.add_paragraph('Таблица 1')
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = 'Наименование'; table.cell(0, 1).text = 'Значение'
    table.cell(1, 0).add_table(rows=1, cols=1)
    before = ET.tostring(table._tbl)
    tree = ET.fromstring(ET.tostring(doc._element))
    report = normalize_elements(tree, 12)
    assert report.tables == 0 and ET.tostring(tree.find('w:body/w:tbl', NS)) == before
    assert any('Сложная' in warning for warning in report.warnings)


def test_captioned_picture_fits_with_notes_without_changing_picture_or_text(tmp_path: Path) -> None:
    doc = Document(); doc.add_heading('Requirements', level=1)
    doc.add_paragraph('См. рисунок Б.1.')
    p = doc.add_paragraph('Приложение Б\nСхема')
    image = io.BytesIO(); Image.new('RGB', (600, 400), 'white').save(image, format='PNG'); image.seek(0)
    run = p.add_run(); run.add_picture(image, width=Inches(10))
    inline = run._r.find('w:drawing/wp:inline', NS)
    original_width, original_height = (int(inline.find(WP+'extent').get(key)) for key in ('cx','cy'))
    inline.tag = WP + 'anchor'
    doc.add_paragraph('Примечание — Уже существующее пояснение.')
    doc.add_paragraph('Рисунок Б.1 — Исходная схема')
    before = doc._element.xpath('.//w:t/text()')
    source, target = tmp_path/'source.docx', tmp_path/'result.docx'
    doc.save(source); report = format_docx(source, target)
    result = Document(target)
    assert result._element.xpath('.//w:t/text()') == before
    assert not result._element.xpath('.//wp:anchor')
    picture = result._element.xpath('.//wp:inline')[0]
    width, height = (int(picture.find(WP+'extent').get(key)) for key in ('cx','cy'))
    assert width < original_width
    assert abs(width / height - original_width / original_height) < 0.00001
    caption = result.paragraphs[-1]
    assert not caption.paragraph_format.keep_with_next
    assert result.paragraphs[-2].paragraph_format.keep_with_next
    assert any('рисунки: 1' in change for change in report.changes)
    assert not any('рисунок Б.1' in warning for warning in report.warnings)
    with ZipFile(source) as a, ZipFile(target) as b:
        assert all(a.read(name) == b.read(name) for name in a.namelist() if name.startswith('word/media/'))


def test_drawing_without_caption_stays_unchanged() -> None:
    doc = Document()
    image = io.BytesIO(); Image.new('RGB', (50,50), 'white').save(image, format='PNG'); image.seek(0)
    p = doc.add_paragraph(); p.add_run().add_picture(image)
    before = ET.tostring(p._p)
    tree = ET.fromstring(ET.tostring(doc._element))
    report = normalize_elements(tree, 12)
    assert report.figures == 0 and ET.tostring(tree.find('w:body/w:p', NS)) == before
    assert any('без однозначной подписи' in warning for warning in report.warnings)


def test_continuation_and_notes_stay_with_records_and_reference_ranges_are_recognized() -> None:
    doc = Document()
    doc.add_paragraph('Сведения приведены в таблицах 1 и 2.')
    doc.add_paragraph('Таблица 1')
    table = doc.add_table(rows=3, cols=2)
    table.cell(0, 0).text = 'Наименование'; table.cell(0, 1).text = 'Значение'
    table.cell(1, 0).text = 'Ток'; table.cell(1, 1).text = '27,5'
    table.cell(2, 0).merge(table.cell(2, 1)).text = 'Примечание — значения сохранены.'
    doc.add_paragraph('Продолжение таблицы 1')
    continuation = doc.add_table(rows=2, cols=2)
    continuation.cell(0, 0).text = 'Наименование'; continuation.cell(0, 1).text = 'Значение'
    doc.add_paragraph('Таблица 2')
    unknown = doc.add_table(rows=2, cols=2)
    unknown.cell(0, 0).text = '1'; unknown.cell(0, 1).text = '0,001'
    tree = ET.fromstring(ET.tostring(doc._element))
    report = normalize_elements(tree, 12)
    rows = tree.find('w:body/w:tbl', NS).findall(W+'tr')
    assert all(node.get(W+'val') == '1' for node in rows[1].xpath('./w:tc/w:p/w:pPr/w:keepNext', namespaces=NS))
    caption = tree.find('w:body', NS).findall(W+'p')[2]
    assert caption.find('w:pPr/w:pageBreakBefore', NS).get(W+'val') == '1'
    assert any('Головка таблицы не определена' in warning for warning in report.warnings)
    assert not any('Проверьте ссылку' in warning for warning in report.warnings)
    assert all(node.get(W+'val') == '0' for node in tree.find('w:body',NS).findall(W+'tbl')[2].xpath('./w:tr/w:trPr/w:tblHeader', namespaces=NS))
