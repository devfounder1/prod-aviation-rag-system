"""Reviewed ГОСТ 2.114 checklist, separated from formatting and conformity.

The supplied edition is pinned. A complete clause/span inventory is an evidence
navigation check, not proof that a TU meets the standard. No technical content,
approvals, legal status or applicability conditions are invented here.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from standards_library import Corpus, Page, pages_hash
from tu_validation import DocumentCheck, TU_SOURCE_SHA256

FORM_LABELS = {'unconfirmed':'Не подтверждено', 'print_framed':'Макет для печати с рамками и штампами',
               'print_frameless':'Бумажный подлинник без рамок', 'electronic':'Электронный конструкторский документ'}
FORMS = frozenset(FORM_LABELS)
CATALOG_PATH = 'reviews/gost_2_114_2016.json'
AUTOMATION = {
    'manual':'Ручная проверка; автоматическое решение не реализовано.',
    'page-size':'Ограниченная автоматическая проверка: измерение размера секций DOCX. Форматы иллюстративных листов и штампы проверяются вручную.',
    'intro':'Автоматическое наблюдение: поиск вводного абзаца. Полнота, точность формулы и соответствие основному КД не проверяются.',
    'references':'Автоматическое наблюдение: найденные обозначения ТУ. Корректность, редакции и содержание ссылок проверяются вручную.',
    'section-outline':'Автоматическое наблюдение: основные заголовки. Состав по ТЗ, порядок, объединение и содержание разделов требуют проверки.',
    'text-profile':'Частичное оформление доступно в выбранном профиле Р 2.105 / Р 2.104. Это не полная реализация ссылочного ГОСТ 2.105 и не доказательство обработки конкретных байтов.',
    'figure-layout':'Частичное оформление существующих однозначно подписанных рисунков. Схема не перерисовывается; связи и достаточность контролирует человек.',
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Span(StrictModel):
    page: int = Field(ge=4,le=14)
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode='after')
    def ordered(self) -> Span:
        if self.end <= self.start:
            raise ValueError('Пустой или обратный диапазон источника')
        return self


class Clause(StrictModel):
    clause: str = Field(pattern=r'^[456](?:\.\d+){1,3}$')
    kind: Literal['heading','requirements']
    spans: tuple[Span,...] = Field(min_length=1)
    span_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class Requirement(StrictModel):
    id: str = Field(pattern=r'^[456](?:\.\d+){1,3}/[a-z0-9-]+$')
    clause: str = Field(pattern=r'^[456](?:\.\d+){1,3}$')
    requirement: str = Field(min_length=1,max_length=1600)
    condition: str = Field(max_length=1000)
    manual_check: str = Field(min_length=1,max_length=1600)
    automation: Literal['manual','page-size','intro','references','section-outline','text-profile','figure-layout']
    dependencies: tuple[str,...]
    form: Literal['any','print','print_framed','print_frameless','electronic']
    modality: Literal['requirement','recommendation','permission']


class PageDisposition(StrictModel):
    pages: tuple[int,...]
    role: str


class ContextReview(StrictModel):
    clauses: tuple[str,...]
    pages: tuple[int,...]
    note: str


class Catalog(StrictModel):
    schema_version: Literal[1]
    review_id: Literal['gost-2-114-2016-supplied-edition-v1']
    reviewed_on: str
    source_id: Literal['gost-2-114-2016']
    source_sha256: Literal['556c15185dd0c00e2310d9b96113b252c27788d1e29215005b49e533a18f45a5']
    text_sha256: Literal['4b480efcb8717fb283ae236eda1ba73a88e35fb062be67a9cd7209429765b9f7']
    pdf_pages: Literal[15]
    scope: str
    page_disposition: tuple[PageDisposition,...]
    context_review: tuple[ContextReview,...]
    referenced_editions: tuple[str,...]
    clauses: tuple[Clause,...]
    requirements: tuple[Requirement,...]

    @model_validator(mode='after')
    def complete_inventory(self) -> Catalog:
        ids=[r.id for r in self.requirements]
        clauses={c.clause:c for c in self.clauses}
        if len(set(ids))!=len(ids) or len(clauses)!=len(self.clauses):
            raise ValueError('Повторяющийся пункт разбора')
        if sorted(p for d in self.page_disposition for p in d.pages)!=list(range(1,16)):
            raise ValueError('Не все страницы источника учтены ровно один раз')
        covered={r.clause for r in self.requirements}
        if covered!={c.clause for c in self.clauses if c.kind=='requirements'}:
            raise ValueError('Нормативный пункт пропущен либо заголовку приписано требование')
        for rule in self.requirements:
            if not rule.id.startswith(rule.clause+'/'):
                raise ValueError('Идентификатор требования не совпадает с пунктом')
            if any(d not in self.referenced_editions for d in rule.dependencies):
                raise ValueError('Неизвестная ссылочная редакция')
        return self


def _unique(pairs: list[tuple[str,Any]]) -> dict[str,Any]:
    result: dict[str,Any]={}
    for key,value in pairs:
        if key in result:
            raise ValueError('Повторяющийся ключ разбора ГОСТ 2.114')
        result[key]=value
    return result


def load_catalog(root: Path | None = None) -> Catalog:
    directory=root if root is not None else Path(__file__).resolve().parent/'standards'
    path=directory/CATALOG_PATH
    if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError('Разбор должен находиться внутри каталога стандартов')
    raw=path.read_bytes()
    if len(raw)>512_000:
        raise ValueError('Слишком большой разбор ГОСТ 2.114')
    return Catalog.model_validate(json.loads(raw,object_pairs_hook=_unique))


def source_inventory(pages: tuple[Page,...]) -> tuple[Clause,...]:
    """Mechanical inventory of numbered source paragraphs, not a rule extractor."""
    chosen={p.number:p.text for p in pages if 4<=p.number<=14}
    if set(chosen)!=set(range(4,15)):
        raise ValueError('Не все нормативные страницы ГОСТ 2.114 доступны')
    starts=[(m[1],p,m.start()) for p,text in sorted(chosen.items())
            for m in re.finditer(r'(?m)^[ \t]*([456](?:\.\d+){1,3})[ \t]+',text)]
    result=[]
    headings={'5.1','5.2','5.3','5.5','5.6','5.7','5.8'}
    for i,(number,page,offset) in enumerate(starts):
        last,end=(starts[i+1][1],starts[i+1][2]) if i+1<len(starts) else (14,len(chosen[14]))
        spans=[];value=''
        for p in range(page,last+1):
            a=offset if p==page else 0;b=end if p==last else len(chosen[p])
            if b>a:
                spans.append(Span(page=p,start=a,end=b));value+=chosen[p][a:b]
        result.append(Clause(clause=number,kind='heading' if number in headings else 'requirements',
                             spans=tuple(spans),span_sha256=hashlib.sha256(value.encode()).hexdigest()))
    return tuple(result)


def verify_inventory(catalog: Catalog,corpus: Corpus) -> None:
    if (corpus.source.sha256!=catalog.source_sha256 or corpus.source.text_sha256!=catalog.text_sha256
            or len(corpus.pages)!=catalog.pdf_pages or pages_hash(corpus.pages)!=catalog.text_sha256
            or source_inventory(corpus.pages)!=catalog.clauses):
        raise ValueError('Пункты/страницы/редакция ГОСТ 2.114 не совпадают с проверенным разбором')


@dataclass(frozen=True)
class ReviewRow:
    rule: Requirement
    pages: tuple[int,...]
    applicability: str
    automation: str
    observations: tuple[DocumentCheck,...]
    outcome: str = 'Нормативное выполнение не подтверждено; нужна ручная проверка.'


@dataclass(frozen=True)
class TUReview:
    candidate_sha256: str
    document_form: str
    catalog: Catalog
    source_available: bool
    inventory_verified: bool
    rows: tuple[ReviewRow,...]

    def render(self,details: bool = True) -> str:
        automatic=sum(r.rule.automation!='manual' for r in self.rows)
        lines=['РАЗБОР ГОСТ 2.114-2016 — предоставленная редакция',
               'DOCX SHA-256: '+self.candidate_sha256,
               'Представление: '+FORM_LABELS[self.document_form],
               f'Учтено номерных пунктов разделов 4–6: {len(self.catalog.clauses)}; контрольных позиций: {len(self.rows)}.',
               'Разделы 1–3, примечания, условия и ссылочные редакции разобраны отдельно.',
               f'Источник доступен: {"да" if self.source_available else "нет"}; совпадение полного перечня пунктов/границ с источником: {"проверено" if self.inventory_verified else "не подтверждено"}.',
               f'Код даёт ограниченную помощь для {automatic} позиций (оформление/измерения/наблюдения). Ручное нормативное заключение требуется для каждой позиции.',
               'Число позиций — не число выполненных требований и не процент соответствия.',
               'Условия (ТЗ, вид поставки, группа изделий, категория заказа, опасности, стадия) автоматически не предполагаются.',
               'Действие редакций и правовая применимость не проверены. Подписи, решения и технические нормы не создаются.']
        if details:
            lines+=['\nКонтекст и ссылки:',*(f'П. {", ".join(c.clauses)}, PDF стр. {c.pages}: {c.note}' for c in self.catalog.context_review),
                    'Редакции, указанные в источнике: '+ '; '.join(self.catalog.referenced_editions),
                    '\nПроверяемые позиции:']
            for row in self.rows:
                rule=row.rule
                lines += [f'\n{rule.id} · PDF стр. {row.pages} · {rule.requirement}',
                          'Применимость: '+row.applicability,
                          'Условие источника/проверки: '+(rule.condition or 'Общее положение для ТУ; учитывать область стандарта и решение по 5.1.2.'),
                          'Автоматизация: '+row.automation,
                          'Вручную: '+rule.manual_check]
                if rule.dependencies:
                    lines.append('Зависимости: '+'; '.join(rule.dependencies))
                for check in row.observations:
                    lines.append(f'Наблюдение [{check.check_id}, {check.status}]: {check.evidence} Область: {check.scope}')
                lines.append('Итог: '+row.outcome)
        return '\n'.join(lines)


def _applicability(rule: Requirement,form: str,available: bool) -> str:
    if not available:
        return 'Источник недоступен: применимость и выполнение не подтверждаются.'
    if rule.form!='any':
        if form=='unconfirmed':
            return 'Требуется подтвердить бумажную/электронную форму и вариант рамок.'
        matches=rule.form==form or (rule.form=='print' and form.startswith('print_'))
        if not matches:
            return 'Другая ветвь оформления; не выбрана для указанного представления.'
    if rule.condition:
        return 'Условие требует подтверждения разработчиком; не признано автоматически выполненным или неприменимым.'
    if rule.modality=='permission':
        return 'Допустимый вариант; проверить основание и выбранное решение.'
    if rule.modality=='recommendation':
        return 'Рекомендация; проверить выбранный вариант и основания отклонения.'
    return 'Подлежит проверке для ТУ в выбранной области; выполнение не установлено.'


def build_review(candidate: bytes,form: str,corpus: Corpus | None,
                 observations: tuple[DocumentCheck,...],root: Path | None = None) -> TUReview:
    if form not in FORMS:
        raise ValueError('Неизвестное представление ТУ')
    catalog=load_catalog(root)
    if corpus is not None:
        if corpus.source.sha256!=TU_SOURCE_SHA256:
            raise ValueError('Разбор применим только к предоставленной редакции ГОСТ 2.114')
        verify_inventory(catalog,corpus)
    pages={c.clause:tuple(s.page for s in c.spans) for c in catalog.clauses}
    rows=[]
    for rule in catalog.requirements:
        available=corpus is not None
        checks=tuple(c for c in observations if available and (
            c.check_id==rule.automation or (rule.automation=='section-outline' and c.check_id.startswith('section-'))))
        if rule.automation=='intro':
            checks=tuple(c for c in observations if available and c.check_id=='intro')
        if _applicability(rule,form,available).startswith('Другая ветвь'):
            checks=()  # Measurements are not evidence for an unselected alternative.
        rows.append(ReviewRow(rule,pages[rule.clause],_applicability(rule,form,available),
                              AUTOMATION[rule.automation],checks))
    return TUReview(hashlib.sha256(candidate).hexdigest(),form,catalog,corpus is not None,
                    corpus is not None,tuple(rows))


def render_catalog(catalog: Catalog) -> str:
    lines=['# ГОСТ 2.114-2016 — перечень проверок ТУ','',
           'Разбор предоставленной редакции, переиздание декабря 2018 г. Это рабочий перечень проверок, не официальный текст стандарта и не заключение о соответствии.',
           '',f'Источник SHA-256: `{catalog.source_sha256}`. Страницы — номера страниц исходного PDF (1–15).',
           '',f'В разделах 4–6 учтены {len(catalog.clauses)} номерных позиций, включая 7 заголовков, и {len(catalog.requirements)} контрольных позиций. Количество не является мерой нормативного покрытия или соответствия.',
           '', 'Форматирование запускает только прежний выбранный профиль Р 2.105 / Р 2.104. Этот перечень ничего автоматически не добавляет в текст ТУ и не меняет рецепт.',
           '', 'Разделы 1–3:']
    lines += ['- '+c.note for c in catalog.context_review]
    lines += ['', 'Ссылочные редакции (наличие новых PDF не означает автоматическую замену):','']
    lines += ['- '+s for s in catalog.referenced_editions]
    previous=''
    pages={c.clause:tuple(s.page for s in c.spans) for c in catalog.clauses}
    for rule in catalog.requirements:
        if rule.clause!=previous:
            lines+=['',f'## Пункт {rule.clause} · PDF страницы {", ".join(map(str,pages[rule.clause]))}','']
            previous=rule.clause
        lines += [f'**{rule.id}** — {rule.requirement}','',
                  '**Условие/вариант:** '+(rule.condition or 'Общее положение; применимость проверяют по виду ТУ и 5.1.2.')+f' Представление: {rule.form}.',
                  '', '**Доступная автоматизация:** '+AUTOMATION[rule.automation],
                  '', '**Ручная проверка:** '+rule.manual_check,'']
        if rule.dependencies:
            lines+=['**Зависимости:** '+'; '.join(rule.dependencies),'']
    return '\n'.join(lines).rstrip()+'\n'
