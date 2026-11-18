"""Conservative coverage inventory bound to exact source and candidate bytes.

An implemented transformation is not an independent check. No model review,
retrieved excerpt or automatic clause candidate can confer a passing status.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

import standards_library as library
from standard_profiles import load_profile
from tu_validation import DocumentCheck, TU_SOURCE_SHA256, validate_tu
from tu_requirements import TUReview, FORMS, build_review
from standard_scopes import load_scopes, scope_note
from text_review import review_text, SOURCE as TEXT_SOURCE
from stamp_review import review_stamps, SOURCE as STAMP_SOURCE

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class RequirementCoverage:
    source_id: str
    designation: str
    source_sha256: str
    rule_id: str
    clauses: tuple[str, ...]
    pdf_pages: tuple[int, ...]
    requirement: str
    exceptions: str
    in_formatting_recipe: bool
    status: str
    reason: str


@dataclass(frozen=True)
class SourceCoverage:
    source_id: str
    designation: str
    sha256: str
    pages: int
    archived: bool
    unit_candidates: int
    textless_pages: tuple[int, ...]
    selected_for_formatting: bool
    note: str


@dataclass(frozen=True)
class CandidateCoverage:
    source_id: str
    source_sha256: str
    page: int
    unit_id: str
    clause_candidate: str | None
    status: str = 'не разобрано'
    applicability: str = 'не определена'


@dataclass(frozen=True)
class CoverageReport:
    candidate_sha256: str
    document_kind: str
    profile_id: str
    sources: tuple[SourceCoverage, ...]
    requirements: tuple[RequirementCoverage, ...]
    blockers: tuple[str, ...]
    candidates: tuple[CandidateCoverage, ...] = ()
    document_checks: tuple[DocumentCheck, ...] = ()
    full_conformance_checked: bool = False
    semantic_catalog_complete: bool = False
    document_form: str = 'unconfirmed'
    tu_review: TUReview | None = None

    def render(self, details: bool = True) -> str:
        available = sum(s.archived for s in self.sources)
        pages = sum(s.pages for s in self.sources if s.archived)
        selected = sum(r.in_formatting_recipe for r in self.requirements)
        kind = {'technical_specifications':'Технические условия','unconfirmed':'Не подтверждён'}[self.document_kind]
        lines = ['ПОКРЫТИЕ ТРЕБОВАНИЙ — не сертификат соответствия',
                 f'Вид документа: {kind}', f'Профиль: {self.profile_id}',
                 f'SHA-256 проверяемого DOCX: {self.candidate_sha256}',
                 f'Полные PDF в локальной библиотеке: {available}/{len(self.sources)}; страниц: {pages}.',
                 f'Записей исходных реестров оформления: {len(self.requirements)}; в рецепте оформления: {selected}.',
                 f'Фрагментов полного каталога, требующих предметного разбора: {len(self.candidates)}.',
                 'Автоматических нормативных заключений «выполнено»: 0.',
                 'Общая библиотека требований по всем ГОСТам ещё не полностью разобрана. Процент соответствия не вычисляется.',
                 'Фрагмент с номером пункта — кандидат для разбора; таблицы, сноски и продолжения требуют проверки.',
                 'Визуальные примеры сохранены в исходных PDF; их геометрия автоматически не интерпретирована.',
                 '\nПробелы и зависимости:', *self.blockers, '\nИсточники:']
        for source in self.sources:
            state = 'PDF и текст сохранены' if source.archived else 'полный источник недоступен'
            lines.append(f'{source.designation}: {state}; {source.pages} страниц; '
                         f'{source.unit_candidates} фрагментов для разбора. {source.note}')
            if source.textless_pages:
                lines.append('Нужны распознавание/просмотр страниц: '+str(source.textless_pages))
        if details:
            if self.document_checks:
                lines.append('\nИзмерения и наблюдения по ТУ (не полное нормативное заключение):')
                for check in self.document_checks:
                    lines.append(f'{check.check_id}: {check.status}; {check.reference}\n'
                                 f'Область: {check.scope}\n{check.evidence}')
            lines.append('\nРазобранные требования (все требуют проверки конкретного документа):')
            for row in self.requirements:
                lines.append(f'{row.designation}, п. {", ".join(row.clauses)}, PDF стр. {row.pdf_pages}; '
                             f'{row.rule_id}: {row.requirement}\n'
                             f'Статус: {row.status}. {row.reason}'+
                             (f' Условия/исключения: {row.exceptions}' if row.exceptions else ''))
        if self.tu_review is not None:
            lines += ['\n'+self.tu_review.render(details)]
        return '\n'.join(lines)


def build_report(candidate: bytes, document_kind: str = 'unconfirmed',
                 corpus_root: Path = library.LIBRARY, standards_root: Path = ROOT/'standards',
                 *, document_form: str = 'unconfirmed') -> CoverageReport:
    if document_kind not in {'unconfirmed', 'technical_specifications'}:
        raise ValueError('Неизвестный вид документа; нужен отдельный проверенный профиль')
    if document_form not in FORMS or (document_kind!='technical_specifications' and document_form!='unconfirmed'):
        raise ValueError('Представление ТУ требует подтверждённого вида документа')
    profile = load_profile(standards_root)
    recipe = json.loads((standards_root/'profiles/eskd_text.json').read_text())
    chosen = {s['sha256']: frozenset(s['rule_ids']) for s in recipe['sources']}
    records = library.sources(standards_root/'library.json')
    scope_plan = load_scopes(standards_root) if document_kind=='technical_specifications' else None
    inventory: list[SourceCoverage] = []
    document_checks: tuple[DocumentCheck, ...] = ()
    tu_corpus: library.Corpus | None = None
    tu_review: TUReview | None = None
    candidates: list[CandidateCoverage] = []
    blockers = ['Применимость каждого требования к этому документу ещё не подтверждена.',
                'Автоматическое форматирование не заменяет проверку результата по пунктам стандарта.',
                'Действие редакций на текущую дату не проверялось; ссылки на другие ГОСТы не заменяют их тексты.']
    if document_kind == 'unconfirmed':
        blockers.append('Вид документа не подтверждён; отчёт не выбирает стандарты по догадке.')
    for source in records:
        try:
            corpus = library.load(source, corpus_root)
        except FileNotFoundError:
            corpus = None
        # Corruption/version mismatch is an error, never silently an absent source.
        archived = corpus is not None
        if source.source_id=='gost-2-114-2016' and source.sha256==TU_SOURCE_SHA256:
            tu_corpus=corpus
        if corpus:
            candidates.extend(CandidateCoverage(source.source_id,source.sha256,u.page,u.unit_id,u.clause_candidate)
                              for u in corpus.units)
        note = ('Выбран прежним рецептом; полная применимость требует проверки.' if source.sha256 in chosen else
                'Не включён в автоматическое оформление; требуется разбор применимости и реализация.')
        if scope_plan is not None:
            note += ' '+scope_note(source,scope_plan)
        if source.source_id=='gost-2-114-2016' and source.sha256==TU_SOURCE_SHA256:
            note += ' Есть отдельный предметный перечень ГОСТ 2.114; он не изменяет рецепт и не подтверждает выполнение требований.'
        if source.source_id == 'gost-2-601-2013':
            note += (' Это отдельная редакция: полученный ГОСТ Р 2.610-2019 ссылается также на '
                     'ГОСТ Р 2.601-2019. Автоматическая подмена на ГОСТ 2.601-2013 не разрешена.')
        inventory.append(SourceCoverage(source.source_id,source.designation,source.sha256,
            source.pdf_pages,archived,len(corpus.units) if corpus else 0,
            tuple(p.number for p in corpus.pages if len(p.text.strip())<100) if corpus else (),
            source.sha256 in chosen,note))
    if document_kind == 'technical_specifications':
        text_source=next((s for s in inventory if s.sha256==TEXT_SOURCE),None)
        if text_source and text_source.archived:
            document_checks=review_text(candidate)
        stamp_source=next((s for s in inventory if s.sha256==STAMP_SOURCE),None)
        if stamp_source and stamp_source.archived:
            document_checks+=review_stamps(candidate,document_form)
        tu = next((s for s in inventory if s.source_id == 'gost-2-114-2016'),None)
        if tu and tu.archived:
            blockers.append('Полный источник ГОСТ 2.114-2016 «Технические условия» сохранён; '
                            'полная проверка состава и содержания ТУ по нему ещё не реализована. '
                            'Применимость этой редакции требует подтверждения.')
            if tu.sha256 == TU_SOURCE_SHA256:
                document_checks+=validate_tu(candidate)
            else:
                blockers.append('Редакция ГОСТ 2.114 отличается от поддерживаемой анализатором; измерения ТУ не выполнялись.')
        else:
            blockers.append('Нет проверенной локальной копии ГОСТ 2.114 «Технические условия»: '
                            'состав и содержание ТУ по нему не проверены.')
        if tu and tu.sha256==TU_SOURCE_SHA256:
            tu_review=build_review(candidate,document_form,tu_corpus,document_checks,standards_root)
        blockers.append('Другие виды документов не применяются к ТУ автоматически.')
    requirements: list[RequirementCoverage] = []
    for name in profile.selected_files:
        if name.startswith('profiles/'):
            continue
        data = json.loads((standards_root/name).read_text())
        sha = data['source']['sha256']
        matched_source = next((s for s in records if s.sha256 == sha), None)
        if matched_source is None:
            raise ValueError('Реестр требований не связан с редакцией из библиотеки')
        for rule in data['rules']:
            selected = rule['id'] in chosen[sha]
            pages = tuple(rule['pdf_pages'])
            if not pages or any(type(p) is not int or not 1<=p<=matched_source.pdf_pages for p in pages):
                raise ValueError('Требование ссылается на неизвестную страницу')
            requirements.append(RequirementCoverage(matched_source.source_id,matched_source.designation,sha,rule['id'],
                tuple(rule['clauses']),pages,rule['requirement'],rule.get('exceptions',''),selected,
                'нужна проверка человеком' if selected else 'проверка не реализована',
                'Есть преобразование в рецепте; нормативная проверка результата ещё не реализована.' if selected else
                'Запись есть в реестре, но этот рецепт не выполняет её проверку или исправление.'))
    return CoverageReport(hashlib.sha256(candidate).hexdigest(),document_kind,profile.profile_id,
                          tuple(inventory),tuple(requirements),tuple(blockers),tuple(candidates),document_checks,
                          document_form=document_form,tu_review=tu_review)


def _json_default(value: Any) -> Any:
    if isinstance(value,BaseModel):
        return value.model_dump(mode='json')
    raise TypeError('Неизвестный тип отчёта')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('document', type=Path)
    parser.add_argument('--kind', choices=['unconfirmed','technical_specifications'], default='unconfirmed')
    parser.add_argument('--form', choices=sorted(FORMS),default='unconfirmed')
    parser.add_argument('--library', type=Path, default=library.LIBRARY)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = build_report(args.document.read_bytes(), args.kind, args.library,document_form=args.form)
    if args.output:
        with args.output.open('x',encoding='utf-8') as stream:
            json.dump(asdict(report),stream,ensure_ascii=False,indent=2,default=_json_default)
    print(report.render())


if __name__ == '__main__':
    main()
