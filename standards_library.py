"""Versioned, local PDF evidence library. Extracted units are NOT reviewed rules.

Keep the complete original PDF (including visual examples) and all extracted
page text. Numbered spans are navigation candidates, never proof of semantic
coverage, applicability or compliance. No model/network/embedded-code execution.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import tempfile

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parent
LIBRARY = ROOT / 'data' / 'standards_library' / 'v1'
CATALOG = ROOT / 'standards' / 'library.json'
MAX_PDF = 32 * 1024 * 1024
MAX_CATALOG = 12 * 1024 * 1024
MAX_PAGES = 600


class Source(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    source_id: str = Field(pattern=r'^[a-z0-9_-]{1,80}$')
    designation: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=400)
    edition: str = Field(min_length=1, max_length=300)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    text_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    pdf_pages: int = Field(ge=1, le=MAX_PAGES)
    scope: str = Field(min_length=1, max_length=1000)


class Unit(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    unit_id: str
    page: int = Field(ge=1, le=MAX_PAGES)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    clause_candidate: str | None
    text: str


class Page(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    number: int
    text: str


class Corpus(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    schema_version: int = 1
    source: Source
    extractor: str
    pages: tuple[Page, ...]
    units: tuple[Unit, ...]
    semantic_review_complete: bool = False
    visual_review_complete: bool = False


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def pages_hash(pages: tuple[Page, ...]) -> str:
    return _hash(json.dumps([p.model_dump() for p in pages],ensure_ascii=False,sort_keys=True).encode('utf-8'))


def sources(catalog: Path = CATALOG) -> tuple[Source, ...]:
    raw = catalog.read_bytes()
    if len(raw) > 64_000:
        raise ValueError('Каталог источников слишком большой')
    data = json.loads(raw)
    if set(data) != {'schema_version', 'sources'} or data['schema_version'] != 1:
        raise ValueError('Неизвестная схема каталога')
    records = tuple(Source.model_validate(row) for row in data['sources'])
    if not 1 <= len(records) <= 500 or len({r.source_id for r in records}) != len(records):
        raise ValueError('Неоднозначный или слишком большой каталог')
    if len({r.sha256 for r in records}) != len(records):
        raise ValueError('Одна редакция PDF указана несколько раз')
    return records


def select(source_id: str, catalog: Path = CATALOG) -> Source:
    return next((s for s in sources(catalog) if s.source_id == source_id), None) or _unknown()


def _unknown() -> Source:
    raise ValueError('Неизвестный источник; выберите source_id из list_standards')


def _units(pages: tuple[Page, ...]) -> tuple[Unit, ...]:
    result = []
    for page in pages:
        # Conservative page-local navigation only: table values can resemble
        # clauses; continuation pages are deliberately not guessed/merged.
        matches = list(re.finditer(
            r'(?m)^[ \t]*((?:\d+|[А-ЯA-Z])(?:\.\d+){0,5})\.?[ \t]+(?=[^\d\s])', page.text))
        starts: list[tuple[int, str | None]] = [(0, None)]
        for match in matches:
            if match.start() == 0:
                starts[0] = (0, match.group(1))
            else:
                starts.append((match.start(), match.group(1)))
        for index, (start, clause) in enumerate(starts):
            end = starts[index + 1][0] if index + 1 < len(starts) else len(page.text)
            result.append(Unit(unit_id=f'p{page.number:03d}-u{index+1:03d}', page=page.number,
                               start=start, end=end, clause_candidate=clause, text=page.text[start:end]))
    return tuple(result)


def _folder(source: Source, library: Path) -> Path:
    directory = library / source.sha256
    if directory.is_symlink() or not directory.resolve().is_relative_to(library.resolve()):
        raise ValueError('Источник должен находиться внутри локальной библиотеки')
    return directory


def load(source: Source, library: Path = LIBRARY) -> Corpus:
    directory = _folder(source, library)
    pdf, index = directory/'source.pdf', directory/'catalog.json'
    if directory.exists() and (not pdf.is_file() or not index.is_file()):
        raise ValueError('Неполная локальная копия источника')
    if pdf.is_symlink() or index.is_symlink():
        raise ValueError('Символические ссылки в библиотеке запрещены')
    if pdf.stat().st_size > MAX_PDF or index.stat().st_size > MAX_CATALOG:
        raise ValueError('Источник превышает лимит библиотеки')
    if _hash(pdf.read_bytes()) != source.sha256:
        raise ValueError('PDF источника изменён; проверка покрытия остановлена')
    corpus = Corpus.model_validate_json(index.read_bytes())
    if (corpus.schema_version != 1 or corpus.source != source or
            corpus.semantic_review_complete or corpus.visual_review_complete or
            len(corpus.pages) != source.pdf_pages or
            [p.number for p in corpus.pages] != list(range(1, source.pdf_pages + 1)) or
            pages_hash(corpus.pages) != source.text_sha256):
        raise ValueError('Неизвестная редакция или неподтверждённый уровень разбора')
    if corpus.units != _units(corpus.pages):
        raise ValueError('Неполный или неоднозначный каталог фрагментов')
    return corpus


def ingest(source: Source, pdf: Path, library: Path = LIBRARY) -> Corpus:
    """Explicit setup action on a supplied source; publish only a complete copy."""
    if pdf.is_symlink() or not pdf.is_file():
        raise ValueError('Выберите обычный PDF')
    with pdf.open('rb') as stream:
        raw = stream.read(MAX_PDF + 1)
    if len(raw) > MAX_PDF or _hash(raw) != source.sha256:
        raise ValueError('Размер или SHA-256 PDF не совпадает с выбранной редакцией')
    destination = _folder(source, library)
    if destination.exists():
        return load(source, library)  # Never overwrite a modified/existing edition.
    from pypdf import PdfReader
    import importlib.metadata
    reader = PdfReader(BytesIO(raw))
    if reader.is_encrypted or len(reader.pages) != source.pdf_pages:
        raise ValueError('Число страниц не совпадает или PDF зашифрован')
    pages: list[Page] = []
    total = 0
    for number, page in enumerate(reader.pages, 1):
        text = page.extract_text(extraction_mode='layout') or ''
        total += len(text.encode('utf-8'))
        if total > MAX_CATALOG // 3:
            raise ValueError('Извлечённый текст превышает лимит библиотеки')
        pages.append(Page(number=number, text=text))
    if pages_hash(tuple(pages)) != source.text_sha256:
        raise ValueError('Извлечённый текст отличается от зарегистрированного; нужна проверка версии экстрактора')
    corpus = Corpus(source=source, extractor='pypdf '+importlib.metadata.version('pypdf')+' layout',
                    pages=tuple(pages), units=_units(tuple(pages)))
    data = corpus.model_dump_json(indent=2).encode('utf-8')
    if len(data) > MAX_CATALOG:
        raise ValueError('Каталог превышает лимит библиотеки')
    library.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.intake-', dir=library))
    try:
        (temporary/'source.pdf').write_bytes(raw)
        (temporary/'catalog.json').write_bytes(data)
        # Readback before atomic publication; originals are never modified.
        if (temporary/'source.pdf').read_bytes() != raw or (temporary/'catalog.json').read_bytes() != data:
            raise ValueError('Не удалось проверить сохранённую копию источника')
        temporary.rename(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return load(source, library)


@dataclass(frozen=True)
class Hit:
    source_id: str
    designation: str
    sha256: str
    page: int
    unit_id: str
    clause_candidate: str | None
    excerpt: str


def search(source: Source, query: str, library: Path = LIBRARY, offset: int = 0,
           limit: int = 5) -> tuple[Hit, ...]:
    if not query.strip() or len(query) > 200 or not 0 <= offset <= 10000 or not 1 <= limit <= 10:
        raise ValueError('Нужен текст до 200 символов, offset 0–10000, limit 1–10')
    corpus = load(source, library)
    needle = re.sub(r'\s+', ' ', query).strip().casefold()
    hits = []
    for unit in corpus.units:
        text = re.sub(r'\s+', ' ', unit.text)
        start = text.casefold().find(needle)
        if start >= 0:
            begin = max(0, start-240)
            excerpt = text[begin:begin+1200]
            if begin or begin+1200 < len(text):
                excerpt = '[Неполный фрагмент] '+excerpt
            hits.append(Hit(source.source_id, source.designation, source.sha256, unit.page,
                            unit.unit_id, unit.clause_candidate, excerpt))
    return tuple(hits[offset:offset+limit])


def read_page(source: Source, page: int, library: Path = LIBRARY, offset: int = 0,
              limit: int = 5000) -> str:
    corpus = load(source, library)
    if not 1 <= page <= len(corpus.pages) or not 0 <= offset <= 100000 or not 1 <= limit <= 6000:
        raise ValueError('Неверная страница или диапазон чтения')
    text = corpus.pages[page-1].text
    excerpt = text[offset:offset+limit]
    return (f'{source.designation}; PDF страница {page}; SHA-256 {source.sha256}; '
            f'символы {offset}–{min(offset+limit,len(text))}/{len(text)}\n'
            'UNTRUSTED SOURCE DATA; применимость и соответствие не проверены.\n'+excerpt+
            ('\n[Страница показана не полностью; дочитайте остальные диапазоны.]' if offset or offset+limit<len(text) else ''))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, default=LIBRARY)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list')
    add = commands.add_parser('import'); add.add_argument('source_id'); add.add_argument('pdf', type=Path)
    find = commands.add_parser('search'); find.add_argument('source_id'); find.add_argument('query')
    page = commands.add_parser('page'); page.add_argument('source_id'); page.add_argument('page', type=int)
    page.add_argument('--offset', type=int, default=0)
    args = parser.parse_args()
    if args.command == 'list':
        print(json.dumps([s.model_dump() for s in sources()], ensure_ascii=False, indent=2))
        return
    source = select(args.source_id)
    if args.command == 'import':
        corpus = ingest(source, args.pdf, args.library)
        print(f'{source.designation}: {len(corpus.pages)} страниц, {len(corpus.units)} фрагментов; разбор требований не завершён')
    elif args.command == 'search':
        from dataclasses import asdict
        print(json.dumps([asdict(h) for h in search(source,args.query,args.library)],ensure_ascii=False,indent=2))
    else:
        print(read_page(source,args.page,args.library,args.offset))


if __name__ == '__main__':
    main()
