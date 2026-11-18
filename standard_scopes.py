"""Source-pinned application order for TU; never an executable rule selector.

Only the reviewed formatting recipe enables code. This plan distinguishes source
scope from implemented rules, particularly drawings and operating documents.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any,Literal

from pydantic import BaseModel,ConfigDict,Field,model_validator

from standards_library import Source,sources


class SourceScope(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    source_id: str=Field(pattern=r'^[a-z0-9-]+$')
    source_sha256: str=Field(pattern=r'^[a-f0-9]{64}$')
    scope_pages: tuple[int,...]=Field(min_length=1)
    purpose: str=Field(min_length=1,max_length=2000)
    stage: Literal['selected_rules','checklist','scope_only']
    state: str=Field(min_length=1,max_length=2000)
    next_step: str=Field(min_length=1,max_length=2000)

    @model_validator(mode='after')
    def honest_stage(self) -> SourceScope:
        if self.stage=='selected_rules' and self.source_id not in {'gost-r-2-105-2019','gost-r-2-104-2023'}:
            raise ValueError('Источник не включён в исполняемый рецепт')
        if self.stage=='checklist' and self.source_id!='gost-2-114-2016':
            raise ValueError('Для источника не подготовлен предметный перечень')
        if any(p<1 for p in self.scope_pages) or len(set(self.scope_pages))!=len(self.scope_pages):
            raise ValueError('Недопустимые страницы области применения')
        return self


class ScopePlan(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    schema_version: Literal[1]
    target: Literal['technical_specifications']
    note: str
    sources: tuple[SourceScope,...]


def _unique(pairs: list[tuple[str,Any]]) -> dict[str,Any]:
    values: dict[str,Any]={}
    for key,value in pairs:
        if key in values:raise ValueError('Повтор ключа плана применимости')
        values[key]=value
    return values


def load_scopes(root: Path | None=None) -> ScopePlan:
    directory=root if root is not None else Path(__file__).resolve().parent/'standards'
    path=directory/'tu_source_scopes.json'
    if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError('План должен находиться внутри каталога стандартов')
    raw=path.read_bytes()
    if len(raw)>128_000:raise ValueError('Слишком большой план применимости')
    plan=ScopePlan.model_validate(json.loads(raw,object_pairs_hook=_unique))
    if len({r.source_id for r in plan.sources})!=len(plan.sources):
        raise ValueError('Источник плана указан повторно')
    return plan


def scope_note(source: Source,plan: ScopePlan) -> str:
    row=next((r for r in plan.sources if r.source_id==source.source_id),None)
    if row is None:return 'Область применения этой редакции ещё не разобрана; правила не включены автоматически.'
    if source.sha256!=row.source_sha256 or any(p>source.pdf_pages for p in row.scope_pages):
        return 'Редакция отличается от разобранной области; применимость не подтверждена, автоматического включения нет.'
    stage={'selected_rules':'Выбранные правила исполняемого профиля',
           'checklist':'Предметный перечень для ручного заключения',
           'scope_only':'Разобрана область; перенос правил ещё не завершён'}[row.stage]
    return f'Для ТУ: {row.purpose} Область: PDF стр. {row.scope_pages}. Этап: {stage}. {row.state} Дальше: {row.next_step}'


def render_plan(root: Path | None=None) -> str:
    plan=load_scopes(root)
    metadata={s.source_id:s for s in sources((root or Path(__file__).resolve().parent/'standards')/'library.json')}
    lines=['# Последовательность переноса ГОСТов для ТУ','',plan.note,'',
           'Форма нашего текущего ТУ: макет для печати с рамками и штампами. Для других запросов вид документа и форма выбираются заново.','',
           'Полное применение всех загруженных стандартов одновременно не заявляется. У каждого стандарта своя область; источники не объединяются в одну инструкцию модели.','']
    for i,row in enumerate(plan.sources,1):
        source=metadata.get(row.source_id)
        if source is None:raise ValueError('Источник плана отсутствует в библиотеке')
        lines+=[f'## {i}. {source.designation}','',scope_note(source,plan),'',f'SHA-256 источника: `{row.source_sha256}`.','']
    return '\n'.join(lines)
