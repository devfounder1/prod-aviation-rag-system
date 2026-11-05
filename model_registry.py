"""
model_registry.py
Singleton-реестр для кэширования тяжелых моделей и компонентов.
Избегает повторной загрузки эмбеддеров, BM25, реранкера.
"""
import logging
from typing import Optional, Dict, Any
from functools import lru_cache

logger = logging.getLogger(__name__)


class ModelRegistry:
    """
    Singleton-реестр моделей.
    Гарантирует, что каждая модель загружается только один раз.
    """
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._embeddings = None
        self._cross_encoder = None
        self._bm25_instances: Dict[str, Any] = {}  # chat_id -> BM25
        
        self._initialized = True
        logger.info("ModelRegistry инициализирован")
    
    @classmethod
    def get_instance(cls) -> 'ModelRegistry':
        """Получить singleton-инстанс."""
        return cls()
    
    def get_embeddings(self):
        """Получить кэшированные эмбеддеры."""
        if self._embeddings is None:
            logger.info("Загрузка эмбеддеров...")
            from langchain_huggingface import HuggingFaceEmbeddings
            
            self._embeddings = HuggingFaceEmbeddings(
                model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                model_kwargs={'device': 'cpu'},
                encode_kwargs={'normalize_embeddings': True}
            )
            logger.info("Эмбеддеры загружены")
        
        return self._embeddings
    
    def get_cross_encoder(self):
        """Получить кэшированный cross-encoder."""
        if self._cross_encoder is None:
            logger.info("Загрузка cross-encoder...")
            from sentence_transformers import CrossEncoder
            
            self._cross_encoder = CrossEncoder(
                'cross-encoder/ms-marco-MiniLM-L-6-v2',
                max_length=512
            )
            logger.info("Cross-encoder загружен")
        
        return self._cross_encoder
    
    def get_bm25(self, chat_id: str, documents: list):
        """Получить или создать BM25 для конкретного чата."""
        if chat_id not in self._bm25_instances:
            logger.info(f"Создание BM25 для чата {chat_id}")
            from langchain_community.retrievers import BM25Retriever
            
            self._bm25_instances[chat_id] = BM25Retriever.from_documents(
                documents,
                k=10
            )
        
        return self._bm25_instances[chat_id]
    
    def clear_bm25_cache(self, chat_id: Optional[str] = None):
        """Очистить кэш BM25."""
        if chat_id:
            self._bm25_instances.pop(chat_id, None)
            logger.info(f"BM25 кэш очищен для чата {chat_id}")
        else:
            self._bm25_instances.clear()
            logger.info("Весь BM25 кэш очищен")
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику кэша."""
        return {
            'embeddings_loaded': self._embeddings is not None,
            'cross_encoder_loaded': self._cross_encoder is not None,
            'bm25_instances': len(self._bm25_instances)
        }


# Глобальная функция для удобства
def get_model_registry() -> ModelRegistry:
    """Получить глобальный реестр моделей."""
    return ModelRegistry.get_instance()