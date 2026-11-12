"""Load one reviewed formatting recipe, never the entire standards library.

Evidence registries are not executable rules. A recipe explicitly selects their
clauses and records project choices separately from normative requirements.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any


# v1 is one reviewed recipe, not a general rule interpreter. Until individual
# transformations can be enabled independently, reject altered selections rather
# than run actions whose supporting clauses have been removed from the recipe.
SUPPORTED_SELECTION: dict[str, frozenset[str]] = {
    'gost_r_2_105_2019.json': frozenset({
        'heading-format', 'heading-clearance', 'section-page-break',
        'body-line-spacing', 'paragraph-indent', 'secondary-font-size',
        'table-caption-position', 'table-header-continuation', 'table-numbering',
        'figure-caption-position', 'figure-numbering',
    }),
    'gost_r_2_104_2023.json': frozenset({
        'textual-forms', 'additional-organization-fields',
    }),
}


@dataclass(frozen=True)
class FormattingProfile:
    profile_id: str
    title: str
    heading_pt: int
    subheading_pt: int
    heading_gap_pt: int
    body_line: float
    indent_mm: float
    table_pt: int
    table_header_pt: int
    selected_files: tuple[str, ...]


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Повторяющийся ключ профиля: ' + key)
        result[key] = value
    return result


def _read(root: Path, name: str) -> dict[str, Any]:
    if not re.fullmatch(r'[a-z0-9_-]+(?:/[a-z0-9_-]+)?\.json', name):
        raise ValueError('Недопустимый путь профиля')
    path = root / name
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Профиль должен находиться в каталоге стандартов')
    raw = path.read_bytes()
    if len(raw) > 128_000:
        raise ValueError('Слишком большой профиль')
    data: Any = json.loads(raw, object_pairs_hook=_unique)
    if not isinstance(data, dict):
        raise ValueError('Некорректный профиль')
    return data


def load_profile(root: Path | None = None) -> FormattingProfile:
    directory = root if root is not None else Path(__file__).resolve().parent / 'standards'
    recipe_name = 'profiles/eskd_text.json'
    recipe = _read(directory, recipe_name)
    if (recipe.get('schema_version') != 1 or recipe.get('profile_id') != 'eskd-text-v1'
            or recipe.get('document_kind') != 'existing_textual_design_document'):
        raise ValueError('Неизвестный вид или версия профиля')
    sources = recipe.get('sources')
    if not isinstance(sources, list) or not 1 <= len(sources) <= 4:
        raise ValueError('Профиль должен явно выбрать от одного до четырёх источников')
    selected = [recipe_name]
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get('file'), str):
            raise ValueError('Не указан источник правила')
        name = source['file']
        if name in selected:
            raise ValueError('Источник выбран дважды')
        evidence = _read(directory, name)
        metadata = evidence.get('source', {})
        if (evidence.get('profile_id') != source.get('profile_id')
                or not isinstance(metadata, dict)
                or metadata.get('sha256') != source.get('sha256')
                or not isinstance(source.get('sha256'), str)
                or not re.fullmatch(r'[0-9a-f]{64}', source['sha256'])):
            raise ValueError('Редакция источника не совпадает с выбранным профилем')
        rules = evidence.get('rules')
        if not isinstance(rules, list) or not all(isinstance(rule, dict) for rule in rules):
            raise ValueError('Некорректный реестр правил')
        identifiers = [rule.get('id') for rule in rules]
        if not all(isinstance(key, str) for key in identifiers) or len(set(identifiers)) != len(identifiers):
            raise ValueError('Неоднозначные идентификаторы правил')
        requested = source.get('rule_ids')
        if (not isinstance(requested, list) or not requested
                or not all(isinstance(key, str) and key in identifiers for key in requested)
                or len(set(requested)) != len(requested)):
            raise ValueError('Выбранное правило отсутствует или повторяется в источнике')
        if frozenset(requested) != SUPPORTED_SELECTION.get(name):
            raise ValueError('Набор правил не поддерживается этим обработчиком; нужен отдельный проверенный профиль')
        selected.append(name)
    if set(selected[1:]) != set(SUPPORTED_SELECTION):
        raise ValueError('Неполный набор источников для выбранного профиля')
    settings = recipe.get('project_choices')
    bounds = {'heading_pt': (14, 24), 'subheading_pt': (12, 20),
              'heading_gap_pt': (20, 48), 'body_line': (1, 2),
              'indent_mm': (12.5, 17), 'table_pt': (10, 14), 'table_header_pt': (10, 14)}
    if not isinstance(settings, dict) or set(settings) != set(bounds):
        raise ValueError('Неполные или неизвестные параметры оформления')
    for key, (minimum, maximum) in bounds.items():
        value = settings[key]
        if type(value) not in {int, float} or not minimum <= value <= maximum:
            raise ValueError('Параметр оформления вне допустимого диапазона: ' + key)
        if key not in {'body_line', 'indent_mm'} and int(value) != value:
            raise ValueError('Размер шрифта и интервал заголовка должны быть целыми')
    if settings['subheading_pt'] >= settings['heading_pt']:
        raise ValueError('Подзаголовок должен быть меньше заголовка раздела')
    title = recipe.get('title')
    if not isinstance(title, str) or not 1 <= len(title) <= 200:
        raise ValueError('Не указано название профиля')
    return FormattingProfile('eskd-text-v1', title, int(settings['heading_pt']),
                             int(settings['subheading_pt']), int(settings['heading_gap_pt']),
                             float(settings['body_line']), float(settings['indent_mm']),
                             int(settings['table_pt']), int(settings['table_header_pt']), tuple(selected))


def runtime_files() -> tuple[str, ...]:
    """Code and selected evidence covered by the host/image freshness check."""
    return ('document_inspection.py', 'gost_formatter.py', 'document_layout.py',
            'document_elements.py', 'standard_profiles.py', 'worker.py',
            *(f'standards/{name}' for name in load_profile().selected_files))
