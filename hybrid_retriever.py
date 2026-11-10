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
from model_registry import get_model_registry
from logging_config import get_logger
logger = get_logger(__name__)
from exceptions import RetrieverError
from retrieval_policy import allow_source

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s : %(message)s')

class HybridRetriever:
    """
    Класс для выполнения гибридного поиска с последующим реранкингом.
    """
    def __init__(self, vector_store_manager: VectorStoreManager):
        self.vector_store_manager = vector_store_manager
        self.vector_store = vector_store_manager.vector_store
        self.documents: list[LangChainDocument] = []
        self.bm25 = None
        self._build_bm25_index()
        
        # Кэшированный cross-encoder из реестра
        self.reranker = get_model_registry().get_cross_encoder()
            
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
                LangChainDocument(page_content=text, metadata=metadata or {})
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
        """
        Гибридный поиск с реранкингом.
        
        Args:
            query: Поисковый запрос
            k: Количество финальных результатов
        
        Returns:
            Список отранжированных документов
        
        Raises:
            RetrieverError: Если поиск не удался
        """
        logger.info("Retrieval started k=%s", k)
        
        k = max(1, int(k))
        candidate_k = max(1, int(k * 3))
        
        if self.vector_store is None:
            raise RetrieverError("Векторная база данных не инициализирована")
        
        logger.info("Parent retrieval k=%s", k)
        
        try:
            # Если BM25 не построен, fallback на чистый векторный поиск
            if self.bm25 is None:
                logging.info("BM25 индекс отсутствует, используем только векторный поиск.")
                return [d for d in self.vector_store_manager.search(query, k=k * 3)
                        if allow_source(str(d.metadata.get("filename", "")), query)][:k]
            
            # ИСПРАВЛЕНО: candidate_k не должен зависеть от self.documents
            # Используем фиксированный лимит или размер BM25 индекса
            if hasattr(self.bm25, 'doc_len'):
                max_docs = len(self.bm25.doc_len)
            else:
                max_docs = len(self.documents)
            
            candidate_k = min(candidate_k, max_docs, 15)
            logger.info(f"candidate_k={candidate_k}, max_docs={max_docs}")
            
            # Векторный поиск
            vector_results = self.vector_store_manager.search(query, k=candidate_k)
            logger.info(f"[RETRIEVER] vector_search вернул {len(vector_results)} документов")
            
            # BM25 поиск
            tokenized_query = query.split()
            bm25_scores = self.bm25.get_scores(tokenized_query)
            top_bm25_indices = np.argsort(bm25_scores)[::-1][:candidate_k]
            bm25_results = [self.documents[i] for i in top_bm25_indices]
            logger.info(f"[RETRIEVER] bm25_search вернул {len(bm25_results)} документов")
            
            vector_results = [d for d in vector_results
                              if allow_source(str(d.metadata.get("filename", "")), query)]
            bm25_results = [d for d in bm25_results
                            if allow_source(str(d.metadata.get("filename", "")), query)]

            # Bring lexical children to the same parent level as vector results.
            parents = []
            seen = set()
            for doc in bm25_results:
                parent_id = doc.metadata.get("parent_id")
                if parent_id and parent_id not in seen:
                    text = self.vector_store_manager.docstore.mget([parent_id])[0]
                    if text:
                        parents.append(LangChainDocument(page_content=text, metadata=doc.metadata))
                        seen.add(parent_id)
                elif not parent_id:
                    parents.append(doc)
            bm25_results = parents

            # RRF fusion
            fused_results = self._reciprocal_rank_fusion(vector_results, bm25_results, k=candidate_k)
            logger.info(f"После RRF fusion: {len(fused_results)} документов")
            
            # Реранкинг
            final_results = self._rerank(query, fused_results, top_k=k)
            logger.info(f"После _rerank: {len(final_results)} документов")
            

            for i, doc in enumerate(final_results):
                fname = doc.metadata.get('filename', '???')
                logger.debug("Final document rank=%s", i)
                        
            return final_results
        
        except RetrieverError:
            raise
        except Exception as e:
            logger.error(f"Ошибка гибридного поиска: {e}", exc_info=True)
            raise RetrieverError(f"Не удалось выполнить поиск: {e}") from e
    
    def _reciprocal_rank_fusion(self, vector_results: List[LangChainDocument], bm25_results: List[LangChainDocument], k: int) -> List[LangChainDocument]:
        import hashlib
        scores: dict[str, float] = {}
        documents: dict[str, LangChainDocument] = {}
        for results in (vector_results, bm25_results):
            seen: set[str] = set()
            for rank, doc in enumerate(results):
                key = str(doc.metadata.get("parent_id") or hashlib.sha256(
                    (str(doc.metadata.get("filename", "")) + "\0" + doc.page_content).encode()
                ).hexdigest())
                if key in seen:
                    continue
                seen.add(key)
                scores[key] = scores.get(key, 0.0) + 1.0 / (61 + rank)
                documents[key] = doc
        return [documents[key] for key in sorted(scores, key=lambda key: scores[key], reverse=True)[:k]]

    def _rerank(self, query: str, documents: List[LangChainDocument], top_k: int) -> List[LangChainDocument]:
        """
        Реранкинг документов через Cross-Encoder.
        
        Args:
            query: Поисковый запрос
            documents: Список документов для ранжирования
            top_k: Количество лучших документов для возврата
        
        Returns:
            Отсортированный список документов
        """
        logger.info(f"Вход: {len(documents)} документов, top_k={top_k}")
        
        if not documents:
            logger.warning("Пустой вход, возвращаем []")
            return []
        
        # Фильтрация отключена — оглавления теперь индексируются
        filtered_docs = documents
        
        if self.reranker is None:
            logger.warning("Реранкер отсутствует, возвращаем топ документов без ранжирования")
            return filtered_docs[:top_k]
        
        # Реранкинг через Cross-Encoder
        pairs = [(query, doc.page_content) for doc in filtered_docs]
        scores = self.reranker.predict(pairs)
        logger.info(f"Получено {len(scores)} оценок от реранкера")
        
        scored_docs = list(zip(filtered_docs, scores))
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        
        final = [doc for doc, score in scored_docs[:top_k]]
        logger.info(f"Возвращаем {len(final)} документов")
        
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