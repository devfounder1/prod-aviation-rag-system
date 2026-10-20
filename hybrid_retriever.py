"""
Модуль гибридного поиска с реранкингом.
Объединяет лексический поиск (BM25), векторный поиск и Cross-Encoder для максимальной точности.
"""
from vector_store import VectorStoreManager
from config import settings
import logging
from typing import List, Tuple
from pathlib import Path
from rank_bm25 import BM25Okapi
from langchain_core.documents import Document as LangChainDocument
import numpy as np

class HybridRetriever:
    """
    Класс для выполнения гибридного поиска с последующим реранкингом.
    """
    
    def __init__(self, vector_store_manager: VectorStoreManager):
        self.vector_store_manager = vector_store_manager
        self.vector_store = vector_store_manager.vector_store
        
        # Для BM25 нам нужны сырые тексты всех документов. 
        # В реальном продакшене это может загружаться из отдельного индекса, 
        # но для простоты мы извлечем их из ChromaDB при инициализации.
        self.documents = []
        self.bm25 = None
        self._build_bm25_index()
        self.reranker = None
        logging.warning("Реранкер отключен. Используем гибридный поиск (BM25 + Vector + RRF).")

        
        #try:
        #    logging.info("Попытка загрузки модели реранкера: BAAI/bge-reranker-v2-m3...")
        #    # Импортируем здесь, чтобы скрипт не падал на этапе импорта, если библиотеки нет
        #    from sentence_transformers import CrossEncoder
        #    self.reranker = CrossEncoder('BAAI/bge-reranker-v2-m3', max_length=512)
        #    logging.info("Модель реранкера успешно загружена.")
        #except Exception as e:
        #    logging.warning(f"Не удалось загрузить реранкер (возможно, проблемы с интернетом): {e}")
        #    logging.info("Будет использоваться только гибридный поиск (BM25 + Vector + RRF).")

    def _build_bm25_index(self):
        """
        Строит индекс BM25 на основе всех документов из векторной базы.
        """
        logging.info("Построение BM25 индекса...")
        
        # Получаем все документы из коллекции ChromaDB
        # limit=None означает "вернуть все документы"        
        all_docs = self.vector_store.get(limit=None)
        
        self.documents = [
            LangChainDocument(page_content=doc, metadata = meta)
            for doc, meta in zip(all_docs['documents'], all_docs['metadatas'])
        ]
        
        tokenizer_docs = [doc.page_content.split() for doc in self.documents]
        self.bm25 = BM25Okapi(tokenizer_docs)
        logging.info(f"BM25 индекс построен для {len(self.documents)} документов")
        
    def search(self, query: str, k: int = None) -> List[LangChainDocument]:
        """
        Полный пайплайн гибридного поиска: BM25 + Vector -> RRF -> Rerank.
        """
        if k is None:
            k = settings.rerank_top_k
        
        # Получаем кандидатов от обоих поисков (берем с запасом, например, 3*k)
        candidate_k = min(k * 3, len(self.documents))  

        # Векторный поиск
        vector_results = self.vector_store_manager.search(query, k = candidate_k)
        
        # BM25 поиск
        tokenized_query = query.split()
        bm25_scores = self.bm25.get_scores(tokenized_query)
        
        # Сортируем индексы по убыванию score
        top_bm25_indices = np.argsort(bm25_scores)[::-1][:candidate_k]
        bm25_results = [self.documents[i] for i in top_bm25_indices]
        
        # Объединяем результаты с помощью RRF (Reciprocal Rank Fusion)
        fused_results = self._reciprocal_rank_fusion(vector_results, bm25_results, k=candidate_k)
        
        # Реранкинг топ-K кандидатов через Cross-Encoder
        final_results = self._rerank(query,fused_results,top_k = k)
        
        return final_results
    
    def _reciprocal_rank_fusion(self, vector_results: List[LangChainDocument], bm25_results: List[LangChainDocument], k: int) -> List[LangChainDocument]:
        """
        Объединяет два ранжированных списка с помощью алгоритма RRF.
        
        Формула RRF: score = sum(1 / (rank + constant))
        constant (обычно 60) сглаживает влияние документов, которые есть только в одном списке.
        """
        
        rrf_scores = {}
        
        # Оцениваем векторные результаты
        for rank, doc in enumerate(vector_results):
            doc_id = id(doc)
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (60 + rank + 1)
        
        # Оцениваем BM25 результаты
        for rank, doc in enumerate(bm25_results):
            doc_id = id(doc)
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (60 + rank + 1)
            
        # Сортируем по итоговому RRF score (по убыванию)
        sorted_items = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        
        # Восстанавливаем объекты документов в новом порядке
        fused_docs = []
        for doc_id, _ in sorted_items[:k]:
            # Ищем документ в одном из списков (он там точно есть)
            for doc in vector_results + bm25_results:
                if id(doc) == doc_id:
                    fused_docs.append(doc)
                    break
                    
        return fused_docs
    
    def _rerank(self, query: str, documents: List[LangChainDocument], top_k: int) -> List[LangChainDocument]:
        """
        Фильтрация мусорных файлов и (опционально) реранкинг.
        """
        if not documents:
            return []
            
        # PRODUCTION HACK: Фильтруем заведомо бесполезные файлы по метаданным
        filtered_docs = [
            doc for doc in documents 
            if "СОДЕРЖАНИЕ" not in doc.metadata.get('filename', '').upper()
        ]
        
        # Если реранкер не загружен, возвращаем топ-K из отфильтрованных результатов
        if self.reranker is None:
            logging.info("Реранкинг пропущен. Возвращаем топ результатов гибридного поиска (после фильтрации).")
            return filtered_docs[:top_k]
            
        # Формируем пары для модели: [(query, doc1), (query, doc2), ...]
        pairs = [(query, doc.page_content) for doc in filtered_docs]
        
        # Модель возвращает массив логитов (оценок релевантности)
        scores = self.reranker.predict(pairs)
        
        # Связываем документы с их оценками
        scored_docs = list(zip(documents, scores))
        
        # Сортируем по оценке (от наибольшей к наименьшей)
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        
        # Возвращаем только документы (без score), топ-K
        return [doc for doc, score in scored_docs[:top_k]]   

# БЫСТРАЯ ПРОВЕРКА МОДУЛЯ
if __name__ == "__main__":
    print("=" * 60)
    print("ТЕСТ ГИБРИДНОГО ПОИСКА С РЕРАНКИНГОМ")
    print("=" * 60)
    
    # 1. Инициализируем векторную базу (загружаем существующую)
    vs_manager = VectorStoreManager()
    vs_manager.load()
    
    # 2. Создаем гибридный ретривер
    retriever = HybridRetriever(vs_manager)
    
    # 3. Тестируем на проблемном запросе
    test_query = "Как включить излучение шкафа 276ГГ02?"
    print(f"\nЗапрос: '{test_query}'\n")
    
    results = retriever.search(query=test_query, k=3)
    
    for i, doc in enumerate(results):
        print(f"Результат #{i+1}:")
        print(f"   Файл: {doc.metadata.get('filename')}")
        print(f"   Текст: {doc.page_content[:200]}...")
        print("-" * 60)