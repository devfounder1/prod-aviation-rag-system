"""
Модуль гибридного поиска с реранкингом.
Объединяет лексический поиск (BM25), векторный поиск и Cross-Encoder для максимальной точности.
"""
from vector_store import VectorStoreManager
from config import settings
import logging
from typing import List
import numpy as np
from rank_bm25 import BM25Okapi
from langchain_core.documents import Document as LangChainDocument

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s : %(message)s')

class HybridRetriever:
    """
    Класс для выполнения гибридного поиска с последующим реранкингом.
    """
    
    def __init__(self, vector_store_manager: VectorStoreManager):
        self.vector_store_manager = vector_store_manager
        self.vector_store = vector_store_manager.vector_store
        
        self.documents = []
        self.bm25 = None
        self._build_bm25_index()
        
        self.reranker = None
        try:
            logging.info("Попытка загрузки модели реранкера: BAAI/bge-reranker-v2-m3...")
            from sentence_transformers import CrossEncoder
            
            # local_files_only=True запрещает любые запросы в интернет
            self.reranker = CrossEncoder(
                'BAAI/bge-reranker-v2-m3', 
                max_length=512, 
                local_files_only=True 
            )
            logging.info("Модель реранкера успешно загружена (оффлайн-режим).")
        except Exception as e:
            logging.warning(f"Не удалось загрузить реранкер: {e}")
            logging.info("Будет использоваться только гибридный поиск (BM25 + Vector + RRF).")
            
    def _build_bm25_index(self):
        logging.info("Построение BM25 индекса...")
        all_docs = self.vector_store.get(limit=None)
        
        self.documents = [
            LangChainDocument(page_content=doc, metadata=meta)
            for doc, meta in zip(all_docs['documents'], all_docs['metadatas'])
        ]
        
        tokenized_docs = [doc.page_content.split() for doc in self.documents]
        self.bm25 = BM25Okapi(tokenized_docs)
        logging.info(f"BM25 индекс построен для {len(self.documents)} документов")
        
    def search(self, query: str, k: int = None) -> List[LangChainDocument]:
        if k is None:
            k = settings.rerank_top_k
        
        candidate_k = min(15, len(self.documents))   

        vector_results = self.vector_store_manager.search(query, k=candidate_k)
        
        tokenized_query = query.split()
        bm25_scores = self.bm25.get_scores(tokenized_query)
        top_bm25_indices = np.argsort(bm25_scores)[::-1][:candidate_k]
        bm25_results = [self.documents[i] for i in top_bm25_indices]
        
        fused_results = self._reciprocal_rank_fusion(vector_results, bm25_results, k=candidate_k)
        final_results = self._rerank(query, fused_results, top_k=k)
        
        return final_results
    
    def _reciprocal_rank_fusion(self, vector_results: List[LangChainDocument], bm25_results: List[LangChainDocument], k: int) -> List[LangChainDocument]:
        rrf_scores = {}
        
        for rank, doc in enumerate(vector_results):
            doc_id = id(doc)
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (60 + rank + 1)
        
        for rank, doc in enumerate(bm25_results):
            doc_id = id(doc)
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (60 + rank + 1)
            
        sorted_items = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        
        fused_docs = []
        for doc_id, _ in sorted_items[:k]:
            for doc in vector_results + bm25_results:
                if id(doc) == doc_id:
                    fused_docs.append(doc)
                    break
                    
        return fused_docs
    
    def _rerank(self, query: str, documents: List[LangChainDocument], top_k: int) -> List[LangChainDocument]:
        if not documents:
            return []
            
        # Фильтруем заведомо бесполезные файлы по метаданным
        filtered_docs = []
        for doc in documents:
            filename = doc.metadata.get('filename', '').upper()
            # Игнорируем: Содержание, файлы со словом "Вопрос" и сырые TXT логи
            if "СОДЕРЖАНИЕ" not in filename and "ВОПРОС" not in filename and not filename.endswith('.TXT'):
                filtered_docs.append(doc)
        
        if self.reranker is None:
            logging.info("Реранкинг пропущен. Возвращаем топ результатов гибридного поиска.")
            return filtered_docs[:top_k]
            
        # Формируем пары для модели строго с отфильтрованными документами
        pairs = [(query, doc.page_content) for doc in filtered_docs]
        scores = self.reranker.predict(pairs)
        
        scored_docs = list(zip(filtered_docs, scores)) # <-- ИСПРАВЛЕНО: zip с filtered_docs
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        
        return [doc for doc, score in scored_docs[:top_k]]     

if __name__ == "__main__":
    print("=" * 60)
    print("ТЕСТ ГИБРИДНОГО ПОИСКА С РЕРАНКИНГОМ")
    print("=" * 60)
    
    vs_manager = VectorStoreManager()
    vs_manager.load()
    
    retriever = HybridRetriever(vs_manager)
    
    test_query = "Как включить излучение шкафа 276ГГ02?"
    print(f"\nЗапрос: '{test_query}'\n")
    
    results = retriever.search(query=test_query, k=3)
    
    for i, doc in enumerate(results):
        print(f"Результат #{i+1}:")
        print(f"   Файл: {doc.metadata.get('filename')}")
        print(f"   Текст: {doc.page_content[:200]}...")
        print("-" * 60)