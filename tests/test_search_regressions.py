from unittest.mock import MagicMock
from langchain_core.documents import Document
from langchain_core.messages import AIMessageChunk
import pytest

from smart_rag import SmartRAG
from retrieval_policy import allow_source


def test_equipment_question_runs_search_even_when_model_would_choose_chat() -> None:
    rag = SmartRAG()
    rag.llm = MagicMock()
    rag.llm.stream.return_value = [AIMessageChunk(content='Synthetic answer')]
    rag.search_documents = MagicMock(return_value=('[Источник: synthetic_manual.txt]\nFictional context', ['synthetic_manual.txt']))
    _, sources = rag.query_stream('Как включить излучение шкафа 276ГГ02?')
    rag.search_documents.assert_called_once()
    assert sources == ['synthetic_manual.txt']
    messages = rag.llm.stream.call_args.args[0]
    assert 'РАЗВЁРНУТЫЙ' in messages[0].content
    assert 'Если пользователь явно просит краткий ответ' in messages[0].content
    assert any('Fictional context' in str(message.content) for message in messages)


@pytest.mark.parametrize('filename', ['0__СОДЕРЖАНИЕ.docx', 'оглавление.pdf', 'table_of_contents.txt'])
def test_navigation_is_only_used_when_requested(filename: str) -> None:
    assert not allow_source(filename, 'Что такое сигнал PPS?')
    assert allow_source(filename, 'Покажи содержание базы документов')
    assert allow_source('synthetic_manual.txt', 'Что такое сигнал PPS?')


def test_attachment_search_drops_navigation_but_preserves_chat_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    import document_processor as dp
    store = MagicMock()
    store.count.return_value = 10
    store.query.return_value = {
        'documents': [['Document list', 'Synthetic factual explanation', 'Synthetic factual explanation']],
        'metadatas': [[{'filename': 'СОДЕРЖАНИЕ.docx'}, {'filename': 'manual.txt'}, {'filename': 'manual.txt'}]],
        'distances': [[0.1, 0.2, 0.2]],
    }
    monkeypatch.setattr(dp, 'UserDocStore', lambda: store)
    monkeypatch.setattr(dp._Embedder, 'embed_query', lambda q: [1.0])
    text = dp.retrieve_user_context('Explain equipment', k=2, chat_id='chat-a')
    assert 'Document list' not in text
    assert text.count('Synthetic factual explanation') == 1
    assert store.query.call_args.args[2] == {'chat_id': 'chat-a'}


def test_contents_questions_still_have_access_to_navigation() -> None:
    assert allow_source('СОДЕРЖАНИЕ.docx', 'Что находится в содержании базы?')


def test_vector_only_fallback_applies_navigation_filter() -> None:
    from hybrid_retriever import HybridRetriever
    manager = MagicMock()
    manager.vector_store = MagicMock()
    manager.search.return_value = [
        Document(page_content='Index only', metadata={'filename': 'contents.txt'}),
        Document(page_content='Fictional facts', metadata={'filename': 'manual.txt'}),
    ]
    retriever = HybridRetriever.__new__(HybridRetriever)
    retriever.bm25 = None
    retriever.vector_store = manager.vector_store
    retriever.vector_store_manager = manager
    result = retriever.search('Explain a technical signal', k=1)
    assert [doc.metadata['filename'] for doc in result] == ['manual.txt']


def test_unrelated_uploads_are_not_sources_for_exact_equipment_questions() -> None:
    from retrieval_policy import allow_attachment_fragment
    assert not allow_attachment_fragment('resume.txt', 'General software engineering experience', 'Как работает 276ГГ02?')
    assert not allow_attachment_fragment('apps.txt', 'Mobile apps overview', 'Что такое PPS?')
    assert allow_attachment_fragment('manual.txt', 'Сигнал PPS2 подаётся на выход', 'Что такое PPS?')
    assert allow_attachment_fragment('manual_276ГГ02.txt', 'Relevant conditions', 'Как работает 276ГГ02?')
    assert allow_attachment_fragment('notes.txt', 'A summary of my document', 'Summarize my document')


def test_generated_acronym_expansions_must_be_present_in_sources() -> None:
    from answer_prompts import strip_unverified_expansions
    context = 'XYZ (Example signal) feeds the ABC board. Duration: 7 (ms).'
    answer = 'XYZ (Example signal), ABC (Invented board expansion). Duration: 7 (ms).'
    cleaned = strip_unverified_expansions(answer, context)
    assert 'XYZ (Example signal)' in cleaned
    assert 'ABC' in cleaned and 'Invented board expansion' not in cleaned
    assert '7 (ms)' in cleaned
    assert strip_unverified_expansions('XYZ (2 ms)', context) == 'XYZ (2 ms)'


def test_search_stream_and_final_answer_strip_unsupported_expansions() -> None:
    rag = SmartRAG()
    rag.route = MagicMock(return_value='SEARCH')
    rag.search_documents = MagicMock(return_value=('[Источник: manual.txt]\nXYZ sends a signal.', ['manual.txt']))
    rag.llm = MagicMock()
    rag.llm.stream.return_value = [AIMessageChunk(content='XYZ (Invented Expansion) sends a signal.')]
    streamed = []
    answer, _ = rag.query_stream('Explain the signal', on_token=streamed.append)
    assert answer == 'XYZ sends a signal.'
    assert streamed[-1] == answer
