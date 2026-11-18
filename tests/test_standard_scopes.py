from __future__ import annotations

from pathlib import Path
import pytest

from standard_scopes import load_scopes,scope_note,render_plan,SourceScope
from standards_library import sources
from standard_profiles import load_profile


def test_all_twelve_sources_have_pinned_scope_and_order_not_automatic_rules() -> None:
    plan=load_scopes();metadata={s.source_id:s for s in sources()}
    assert set(metadata)=={s.source_id for s in plan.sources}
    for row in plan.sources:
        assert row.source_sha256==metadata[row.source_id].sha256
        assert all(1<=p<=metadata[row.source_id].pdf_pages for p in row.scope_pages)
    assert {r.source_id for r in plan.sources if r.stage=='selected_rules'}=={'gost-r-2-105-2019','gost-r-2-104-2023'}
    assert 'tu_source_scopes.json' not in load_profile().selected_files
    assert render_plan()==Path('docs/gost-application-order.md').read_text()


def test_scope_does_not_silently_follow_replaced_edition() -> None:
    source=next(s for s in sources() if s.source_id=='gost-r-2-106-2019')
    changed=source.model_copy(update={'sha256':'0'*64})
    assert 'Редакция отличается' in scope_note(changed,load_scopes())
    assert 'ещё не разобрана' in scope_note(source.model_copy(update={'source_id':'unknown'}),load_scopes())


def test_irrelevant_source_cannot_claim_formatter_is_enabled() -> None:
    data=next(s for s in load_scopes().sources if s.source_id=='gost-2-414-75').model_dump()
    data['stage']='selected_rules'
    with pytest.raises(ValueError):SourceScope.model_validate(data)
