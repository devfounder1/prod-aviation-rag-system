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
        """Построение BM25 индекса с защитой от лимита SQLite в ChromaDB"""
        logging.info("Построение BM25 индекса...")
        try:
            texts = []
            metadatas = []
            limit = 1000  # Безопасный лимит для SQLite
            offset = 0
            
            # Получаем документы порциями
            while True:
                collection_data = self.vector_store.get(limit=limit, offset=offset, include=['documents', 'metadatas'])
                batch_texts = collection_data.get('documents', [])
                batch_metadatas = collection_data.get('metadatas', [])
                
                if not batch_texts:
                    break
                    
                texts.extend(batch_texts)
                metadatas.extend(batch_metadatas)
                
                if len(batch_texts) < limit:
                    break  # Это была последняя порция
                    
                offset += limit
            
            if not texts:
                logging.warning("Векторная база пуста. BM25 индекс не построен.")
                self.bm25 = None
                return
            
            # 🆕 СОХРАНЯЕМ документы в self.documents с метаданными
            self.documents = [
                LangChainDocument(page_content=text, metadata=metadata)
                for text, metadata in zip(texts, metadatas)
            ]
            
            # texts - это список строк, делаем .split() для каждой
            tokenized_docs = [text.split() for text in texts]
            self.bm25 = BM25Okapi(tokenized_docs)
            logging.info(f"BM25 индекс успешно построен для {len(texts)} документов")
            logging.info(f"Сохранено {len(self.documents)} документов в self.documents")
            
        except Exception as e:
            logging.error(f"Ошибка при построении BM25 индекса: {e}")
            self.bm25 = None
        
    def search(self, query: str, k: int = 5) -> List[LangChainDocument]:
        print(f"[RETRIEVER] search() вызван с query='{query[:50]}...', k={k}", flush=True)
        
        # ЖЕСТКАЯ ЗАЩИТА: k и candidate_k никогда не могут быть 0 или отрицательными
        k = max(1, int(k))
        candidate_k = max(1, int(k * 3))
        
        if self.vector_store is None:
            raise RuntimeError("Векторная база данных не инициализирована")
            
        logging.info(f"Поиск по запросу: '{query}' (топ-{k} родителей)")
        
        # Если BM25 не построен, fallback на чистый векторный поиск
        if self.bm25 is None:
            logging.info("BM25 индекс отсутствует, используем только векторный поиск.")
            return self.vector_store_manager.search(query, k=k)
        
        # 🆕 ИСПРАВЛЕНО: candidate_k не должен зависеть от self.documents
        # Используем фиксированный лимит или размер BM25 индекса
        if hasattr(self.bm25, 'doc_len'):
            max_docs = len(self.bm25.doc_len)
        else:
            max_docs = len(self.documents)
        
        candidate_k = min(candidate_k, max_docs, 15)
        print(f"[RETRIEVER] candidate_k={candidate_k}, max_docs={max_docs}", flush=True)
        
        # Векторный поиск
        vector_results = self.vector_store_manager.search(query, k=candidate_k)
        print(f"[RETRIEVER] vector_search вернул {len(vector_results)} документов", flush=True)
        
        # BM25 поиск
        tokenized_query = query.split()
        bm25_scores = self.bm25.get_scores(tokenized_query)
        top_bm25_indices = np.argsort(bm25_scores)[::-1][:candidate_k]
        bm25_results = [self.documents[i] for i in top_bm25_indices]
        print(f"[RETRIEVER] bm25_search вернул {len(bm25_results)} документов", flush=True)
        
        # RRF fusion
        fused_results = self._reciprocal_rank_fusion(vector_results, bm25_results, k=candidate_k)
        print(f"[RETRIEVER] После RRF fusion: {len(fused_results)} документов", flush=True)
        
        # Реранкинг
        final_results = self._rerank(query, fused_results, top_k=k)
        print(f"[RETRIEVER] После _rerank: {len(final_results)} документов", flush=True)
        
        # Финальная отладка
        for i, doc in enumerate(final_results):
            fname = doc.metadata.get('filename', '???')
            print(f"[RETRIEVER] Финальный документ [{i}]: filename='{fname}'", flush=True)
        
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
        print(f"[RETRIEVER._rerank] Вход: {len(documents)} документов, top_k={top_k}", flush=True)
        
        if not documents:
            print(f"[RETRIEVER._rerank] Пустой вход, возвращаем []", flush=True)
            return []
        
        # ФИЛЬТРАЦИЯ файлов-оглавлений
        skip_patterns = ['содержание', 'contents', 'оглавление', 'table_of_contents', '0__содержание']
        filtered_docs = []
        for doc in documents:
            filename = doc.metadata.get('filename', '').lower()
            if any(pattern in filename for pattern in skip_patterns):
                print(f"[RETRIEVER._rerank] Исключен файл-оглавление: {filename}", flush=True)
                continue
            filtered_docs.append(doc)
        
        print(f"[RETRIEVER._rerank] После фильтрации оглавлений: {len(filtered_docs)} документов", flush=True)
        
        if not filtered_docs:
            print(f"[RETRIEVER._rerank] Все документы отфильтрованы, возвращаем оригинальный список", flush=True)
            filtered_docs = documents
        
        if self.reranker is None:
            print(f"[RETRIEVER._rerank] Реранкер отсутствует, возвращаем топ {top_k}", flush=True)
            return filtered_docs[:top_k]
        
        # Реранкинг
        pairs = [(query, doc.page_content) for doc in filtered_docs]
        scores = self.reranker.predict(pairs)
        print(f"[RETRIEVER._rerank] Получено {len(scores)} оценок от реранкера", flush=True)
        
        scored_docs = list(zip(filtered_docs, scores))
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        
        final = [doc for doc, score in scored_docs[:top_k]]
        print(f"[RETRIEVER._rerank] Возвращаем {len(final)} документов", flush=True)
        
        return final    

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