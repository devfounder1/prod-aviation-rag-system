"""Reproducible, private-data-free RAG benchmark. --live uses only local models."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Any, cast

import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

FIXTURE = Path(__file__).parent / 'tests' / 'fixtures' / 'rag_benchmark.json'


class FixtureEmbeddings(Embeddings):
    """Deterministic lexical vectors for CI plumbing, not semantic-quality evidence."""
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        output = []
        for text in texts:
            vector = [0.0] * 256
            for token, count in Counter(re.findall(r'\w+', text.lower())).items():
                vector[int(hashlib.sha256(token.encode()).hexdigest(), 16) % 256] += count
            output.append(vector)
        return output

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def grade(case: dict[str, Any], answer: str, sources: list[str],
          retrieved: list[str]) -> dict[str, bool]:
    expected = case['expected_source']
    return {
        'retrieval_hit': expected is None or expected in retrieved,
        'facts_present': all(re.search(r'(?<!\w)' + re.escape(fact) + r'(?!\w)', answer) for fact in case['facts']),
        'citation_correct': expected is None or (expected in answer and expected in sources and
            all(name in retrieved for name in re.findall(r'[\w.-]+\.(?:txt|pdf|docx)', answer))),
        'abstention_correct': not case['abstain'] or bool(re.search(
            r'не указан|не содерж|нет (?:данных|информации)|недостаточно|отсутств|not (?:provided|specified)|unknown',
            answer.lower())),
    }


def run_benchmark(live: bool = False) -> dict[str, Any]:
    fixture = json.loads(FIXTURE.read_text())
    embeddings: Embeddings = FixtureEmbeddings()
    if live:
        from model_registry import get_model_registry
        embeddings = get_model_registry().get_embeddings()
    docs = [Document(page_content=item['text'], metadata={'filename': item['filename'],
             'parent_id': str(i)}) for i, item in enumerate(fixture['documents'])]
    with tempfile.TemporaryDirectory(prefix='butuz-eval-') as directory:
        client = chromadb.PersistentClient(path=directory,
                    settings=ChromaSettings(anonymized_telemetry=False))
        vector = Chroma.from_documents(docs, embeddings, client=client, collection_name='fixture_eval')
        # Use the production hybrid retriever with a tiny independent document manager.
        from hybrid_retriever import HybridRetriever
        from vector_store import VectorStoreManager
        class Parents:
            def mget(self, keys: list[str]) -> list[str]:
                return [docs[int(key)].page_content for key in keys]
        class Manager:
            vector_store = vector
            docstore = Parents()
            def search(self, query: str, k: int = 3) -> list[Document]:
                return vector.similarity_search(query, k=min(k, len(docs)))
        # Avoid loading an ML reranker in deterministic CI mode.
        if live:
            retriever = HybridRetriever(cast(VectorStoreManager, Manager()))
        else:
            retriever = HybridRetriever.__new__(HybridRetriever)
            retriever.vector_store_manager = cast(VectorStoreManager, Manager())
            retriever.vector_store = vector
            retriever.documents = []
            retriever.bm25 = None
            retriever.reranker = None
            retriever._build_bm25_index()
        rag: Any = None
        if live:
            from smart_rag import SmartRAG
            rag = SmartRAG()
            rag.route = lambda *args: 'SEARCH'
            rag.llm = rag.llm.bind(max_tokens=220)
        cases = []
        for case in fixture['cases']:
            found = retriever.search(case['question'], k=1)
            names = [d.metadata['filename'] for d in found]
            answer, sources = '', names
            if live:
                def search_fixture(question: str, chat_id: str) -> tuple[str, list[str]]:
                    return '\n\n'.join(f"[Источник: {d.metadata['filename']}]\n{d.page_content}" for d in found), names
                rag.search_documents = search_fixture
                answer, sources = rag.query_stream(case['question'], chat_id='fixture-eval')
            checks = grade(case, answer, sources, names) if live else {
                'retrieval_hit': case['expected_source'] is None or case['expected_source'] in names}
            cases.append({'id': case['id'], 'retrieved': names, 'answer': answer, 'checks': checks})
        positive = [r for r, c in zip(cases, fixture['cases']) if not c['abstain']]
        negative = [r for r, c in zip(cases, fixture['cases']) if c['abstain']]
        metrics = {'source_recall_at_1': sum(c['checks']['retrieval_hit'] for c in positive) / len(positive)}
        if live:
            metrics.update({
                'fact_accuracy': sum(c['checks']['facts_present'] for c in positive) / len(positive),
                'citation_accuracy': sum(c['checks']['citation_correct'] for c in positive) / len(positive),
                'abstention_accuracy': sum(c['checks']['abstention_correct'] for c in negative) / len(negative)})
        return {'mode': 'local-model-quality' if live else 'deterministic-ci-plumbing',
                'private_data_used': False, 'metrics': metrics, 'cases': cases,
                'passed': all(all(c['checks'].values()) for c in cases)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='Use local Ollama, embeddings and reranker')
    parser.add_argument('--output', type=Path, default=Path('eval-results/rag.json'))
    args = parser.parse_args()
    report = run_benchmark(args.live)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'mode': report['mode'], 'metrics': report['metrics'], 'passed': report['passed']}))
    raise SystemExit(0 if report['passed'] else 1)
