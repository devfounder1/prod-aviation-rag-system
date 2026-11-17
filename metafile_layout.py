"""Derived EMF presentation for a narrowly supported legacy GOST font.

Retain the source part verbatim. Change only font-face/average-width fields and
the optional per-character spacing pointer in a new display copy. Drawing
commands, text strings, anchors and connection geometry are never regenerated.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import PurePosixPath
import statistics
import struct
from typing import Any
from zipfile import ZipFile

from lxml import etree as ET  # type: ignore[import-untyped]

from document_elements import FIGURE

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
NS = {'w': W, 'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture'}
SUPPORTED_RECORDS = {1, 14, 18, 24, 27, 37, 38, 39, 40, 42, 54, 82, 84, 86}


@dataclass(frozen=True)
class FontRepair:
    data: bytes
    fonts: int
    text_runs: int


class UnsupportedMetafile(ValueError):
    """Keep an unsupported metafile intact instead of approximating its output."""


def repair_emf(raw: bytes) -> FontRepair | None:
    if len(raw) < 88 or raw[40:44] != b' EMF' or 'GOST'.encode('utf-16-le') not in raw:
        return None
    if len(raw) > 4_000_000 or struct.unpack_from('<I', raw, 48)[0] != len(raw):
        raise UnsupportedMetafile('Некорректный размер EMF')
    records: list[tuple[int, int, int]] = []
    position = 0
    while position < len(raw):
        if position + 8 > len(raw):
            raise UnsupportedMetafile('Оборванная запись EMF')
        kind, size = struct.unpack_from('<II', raw, position)
        if size < 8 or size % 4 or position + size > len(raw) or len(records) >= 50_000:
            raise UnsupportedMetafile('Некорректная запись EMF')
        if kind not in SUPPORTED_RECORDS:
            raise UnsupportedMetafile('Сложные команды EMF требуют ручной проверки')
        records.append((position, kind, size)); position += size
    if (records[0][1] != 1 or records[0][2] < 88 or records[-1][1] != 14
            or len(records) != struct.unpack_from('<I', raw, 52)[0]):
        raise UnsupportedMetafile('Некорректный заголовок или конец EMF')
    # Object handles can be deleted/reused. Associate each text with its exact
    # font-creation record, rather than a process-global font-name registry.
    objects: dict[int, tuple[int, int] | None] = {}
    non_fonts: set[int] = set()
    selected: tuple[int, int] | None = None
    spacing: dict[int, list[float]] = {}
    output_records: list[int] = []
    for offset, kind, size in records:
        if kind in {37, 38, 39, 40, 82} and size < 12:
            raise UnsupportedMetafile('Оборванный объект EMF')
        if kind == 82:
            if size < 104:
                raise UnsupportedMetafile('Оборванное описание шрифта')
            handle = struct.unpack_from('<I', raw, offset + 8)[0]
            non_fonts.discard(handle)
            try:
                face = raw[offset + 40:offset + 104].decode('utf-16-le').split('\0')[0]
            except UnicodeDecodeError as exc:
                raise UnsupportedMetafile('Некорректное имя шрифта') from exc
            height, _, angle, orientation = struct.unpack_from('<iiii', raw, offset + 12)
            if face == 'GOST':
                if not 4 <= abs(height) <= 128 or angle or orientation:
                    raise UnsupportedMetafile('Поворот или масштаб шрифта не поддерживается')
                objects[handle] = (offset, abs(height))
            else:
                objects[handle] = None
        elif kind == 37:
            handle = struct.unpack_from('<I', raw, offset + 8)[0]
            if handle in objects:
                selected = objects[handle]
            elif handle in {0x80000000 | value for value in (10, 11, 12, 13, 14, 16, 17)}:
                selected = None
            elif handle not in non_fonts and not (handle & 0x80000000):
                raise UnsupportedMetafile('Неизвестный объект EMF')
        elif kind in {38, 39}:
            handle = struct.unpack_from('<I', raw, offset + 8)[0]
            objects.pop(handle, None); non_fonts.add(handle)
        elif kind == 40:
            handle = struct.unpack_from('<I', raw, offset + 8)[0]
            old = objects.pop(handle, None); non_fonts.discard(handle)
            if old is not None and old == selected:
                selected = None
        elif kind == 84 and selected is not None:
            if size < 76:
                raise UnsupportedMetafile('Оборванный текст EMF')
            count, string_at, options = struct.unpack_from('<III', raw, offset + 44)
            dx_at = struct.unpack_from('<I', raw, offset + 72)[0]
            if (not 1 <= count <= 4096 or options != 0 or string_at < 76
                    or string_at + count * 2 > size or dx_at < string_at + count * 2
                    or dx_at + count * 4 > size):
                raise UnsupportedMetafile('Неподдерживаемое размещение текста EMF')
            try:
                text = raw[offset + string_at:offset + string_at + count * 2].decode('utf-16-le')
            except UnicodeDecodeError as exc:
                raise UnsupportedMetafile('Некорректный текст EMF') from exc
            if len(text) != count or '\0' in text:
                raise UnsupportedMetafile('Глифы EMF требуют ручной проверки')
            advances = struct.unpack_from('<' + 'i' * count, raw, offset + dx_at)
            if min(advances) < 0 or max(advances) > selected[1] * 4 or not sum(advances):
                raise UnsupportedMetafile('Необычные интервалы EMF')
            spacing.setdefault(selected[0], []).append(sum(advances) / count)
            output_records.append(offset)
    if not spacing:
        return None
    result = bytearray(raw)
    for offset, averages in spacing.items():
        width = max(1, round(statistics.median(averages)))
        struct.pack_into('<i', result, offset + 16, width)
        result[offset + 40:offset + 104] = 'Liberation Sans'.encode('utf-16-le').ljust(64, b'\0')
    for offset in output_records:
        # The original character strings and DX arrays remain in the record;
        # zero selects natural metrics for the locally supplied substitute font.
        struct.pack_into('<I', result, offset + 72, 0)
    return FontRepair(bytes(result), len(spacing), len(output_records))


def repair_figure_fonts(document: Any, package: ZipFile) -> tuple[dict[str, bytes], int, tuple[str, ...]]:
    body = document.find('{' + W + '}body')
    relationship_name = 'word/_rels/document.xml.rels'
    if body is None or relationship_name not in package.namelist():
        return {}, 0, ()
    parser = ET.XMLParser(resolve_entities=False, no_network=True)
    relationships = ET.fromstring(package.read(relationship_name), parser)
    content_types = ET.fromstring(package.read('[Content_Types].xml'), parser)
    by_id = {rel.get('Id'): rel for rel in relationships}
    updates: dict[str, bytes] = {}
    count = 0
    warnings: list[str] = []
    blocks = list(body)
    for index, paragraph in enumerate(blocks):
        if paragraph.tag != '{' + W + '}p':
            continue
        pictures = paragraph.xpath('./w:r/w:drawing//pic:pic', namespaces=NS)
        if len(pictures) != 1:
            continue
        following = []
        for block in blocks[index + 1:index + 10]:
            if block.tag != '{' + W + '}p' or block.xpath('.//w:drawing | .//w:pict | .//w:object', namespaces=NS):
                break
            following.append(''.join(block.xpath('.//w:t/text()', namespaces=NS)).strip())
        if not any(FIGURE.match(text) for text in following):
            continue
        blips = pictures[0].xpath('./pic:blipFill/a:blip', namespaces=NS)
        if len(blips) != 1:
            continue
        blip = blips[0]
        relation = by_id.get(blip.get('{' + R + '}embed'))
        if relation is None or relation.get('TargetMode', 'Internal') != 'Internal':
            continue
        target = relation.get('Target', '')
        path = PurePosixPath(target)
        if len(path.parts) != 2 or path.parts[0] != 'media' or '\\' in target:
            continue
        part = 'word/' + target
        if part not in package.namelist():
            continue
        try:
            repair = repair_emf(package.read(part))
        except UnsupportedMetafile as exc:
            warnings.append('Шрифт старой схемы оставлен без изменения: ' + str(exc))
            continue
        if repair is None:
            continue
        digest = hashlib.sha256(repair.data).hexdigest()
        derived = 'word/media/butuz-font-' + digest + '.emf'
        if derived in package.namelist() and package.read(derived) != repair.data:
            raise ValueError('Конфликт части с исправленным отображением шрифта')
        updates[derived] = repair.data
        identifier = 'rIdButuzFont' + digest
        existing = by_id.get(identifier)
        if existing is not None and existing.get('Target') != derived[5:]:
            raise ValueError('Конфликт ссылки на исправленный рисунок')
        if existing is None:
            existing = ET.SubElement(relationships, '{' + REL + '}Relationship',
                                     Id=identifier, Target=derived[5:], Type=R + '/image')
            by_id[identifier] = existing
        if not any(node.get('PartName') == '/' + derived for node in content_types):
            ET.SubElement(content_types, '{' + CT + '}Override',
                          PartName='/' + derived, ContentType='image/x-emf')
        blip.set('{' + R + '}embed', identifier)
        count += 1
    if count:
        updates[relationship_name] = ET.tostring(relationships, encoding='UTF-8', xml_declaration=True, standalone=True)
        updates['[Content_Types].xml'] = ET.tostring(content_types, encoding='UTF-8', xml_declaration=True, standalone=True)
    return updates, count, tuple(warnings)
