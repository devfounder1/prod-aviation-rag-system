"""
model_registry.py
Singleton-реестр для кэширования тяжелых моделей и компонентов.
Избегает повторной загрузки эмбеддеров, BM25, реранкера.

ВАЖНО: Все модели загружаются ТОЛЬКО из локального кэша (local_files_only=True).
Никаких скачиваний из интернета в рантайме!
"""
import logging
from typing import Optional, Dict, Any

from config import settings

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
        self._bm25_instances: Dict[str, Any] = {}
        
        self._initialized = True
        logger.info("ModelRegistry инициализирован")
    
    @classmethod
    def get_instance(cls) -> 'ModelRegistry':
        """Получить singleton-инстанс."""
        return cls()
    
    def get_embeddings(self):
        """Получить кэшированные эмбеддеры. ТОЛЬКО локальная загрузка."""
        if self._embeddings is None:
            logger.info(f"Загрузка эмбеддеров: {settings.embedder_model_name} (device={settings.embedder_device})")
            from langchain_huggingface import HuggingFaceEmbeddings
            
            self._embeddings = HuggingFaceEmbeddings(
                model_name=settings.embedder_model_name,
                model_kwargs={
                    'device': settings.embedder_device,
                    'local_files_only': True,  # ← КРИТИЧНО: запрет скачивания из интернета
                },
                encode_kwargs={'normalize_embeddings': True},
            )
            logger.info("Эмбеддеры загружены из локального кэша")
        
        return self._embeddings
    
    def get_cross_encoder(self):
        """Получить кэшированный cross-encoder. ТОЛЬКО локальная загрузка."""
        if self._cross_encoder is None:
            # Имя модели захардкожено (как в оригинальном hybrid_retriever.py)
            reranker_name = 'BAAI/bge-reranker-v2-m3'
            logger.info(f"Загрузка cross-encoder: {reranker_name}")
            try:
                from sentence_transformers import CrossEncoder
                
                self._cross_encoder = CrossEncoder(
                    reranker_name,
                    max_length=512,
                    local_files_only=True,
                )
                logger.info("Cross-encoder загружен из локального кэша")
            except Exception as e:
                logger.warning(f"Не удалось загрузить реранкер: {e}")
                logger.info("Будет использоваться только гибридный поиск (BM25 + Vector + RRF).")
                self._cross_encoder = None
        
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


def get_model_registry() -> ModelRegistry:
    """Получить глобальный реестр моделей."""
    return ModelRegistry.get_instance()