"""
Модуль для управления векторной базой данных ChromaDB.
Отвечает за создание, сохранение и загрузку эмбеддингов документов.
"""
from data_ingestion import DocumentIngestor   
import logging
from pathlib import Path
from typing import List, Optional
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document as LangChainDocument
from config import settings
from langchain.retrievers import ParentDocumentRetriever
from langchain.storage import InMemoryStore # Или LocalFileStore для сохранения на диск
from langchain_text_splitters import RecursiveCharacterTextSplitter

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s : %(message)s')
    
class VectorStoreManager:
    """
    Менеджер векторной базы данных.
    
    Отвечает за:
    1. Инициализацию модели эмбеддингов
    2. Создание новой базы из документов (с сохранением на диск)
    3. Загрузку существующей базы (без пересчёта эмбеддингов)
    4. Поиск похожих документов по запросу
    """
    def __init__(self):
        logging.info(f"Загрузка модели эмбеддингов: {settings.embedder_model_name}")
        
        self.embeddings = HuggingFaceEmbeddings(
            model_name=settings.embedder_model_name,
            model_kwargs={
                'device': settings.embedder_device,
                'local_files_only': True  # ДОБАВЛЕНО: Запрещает любые запросы в интернет
            },
            encode_kwargs={'normalize_embeddings': True},
        )
        
        self.vector_store: Optional[Chroma] = None
        logging.info("Модель эмбеддингов загружена (оффлайн-режим).")
    
    def create(self, documents: List[LangChainDocument]) -> Chroma:
        """
        Создание новой векторной базы из списка документов.
        
        Процесс:
        1. Для каждого документа вычисляется эмбеддинг (вектор)
        2. Векторы + метаданные + исходный текст сохраняются в ChromaDB
        3. База сохраняется на диск в persist_directory
        
        Args:
            documents: Список объектов LangChain Document с текстом и метаданными
            
        Returns:
            Chroma: Объект векторной базы данных
        """
        logging.info(f"Создание векторной базы из {len(documents)} документов")
        persist_path = Path(settings.chroma_persist_dir)
        if persist_path.exists():
            logging.warning(f"Папка {persist_path} уже существует. База будет перезаписана.")        
        
        self.vector_store = Chroma.from_documents(
            documents=documents,
            embedding=self.embeddings,
            persist_directory=settings.chroma_persist_dir,
            collection_name="PRL27_technical_docs"
        )
        
        logging.info(f"Векторная база создана и сохранена в: {persist_path.absolute()}")
        return self.vector_store
    
    def load(self) -> Chroma:
        """
        Загрузка существующей векторной базы с диска.
            
        Эмбеддинги НЕ пересчитываются — они уже сохранены в базе.
        Загружается только объект для выполнения поиска.
            
        Returns:
            Chroma: Объект векторной базы данных
        """ 

        persist_path = Path(settings.chroma_persist_dir)
        
        if not persist_path.exists():
            raise FileNotFoundError(
                f"Векторная база не найдена по пути: {persist_path.absolute()}\n"
                f"Сначала создайте базу через метод create()"
            )
        
        logging.info(f"Загрузка векторной базы из: {persist_path.absolute()}")
        
        self.vector_store = Chroma(
            persist_directory=settings.chroma_persist_dir,
            collection_name="PRL27_technical_docs",
            embedding_function=self.embeddings
        )

        logging.info("Векторная база загружена")
        return self.vector_store

    def search(self, query: str, k: int = None) -> List[LangChainDocument]:
        """
        Поиск наиболее похожих документов по запросу.
        
        Процесс:
        1. Запрос превращается в вектор через ту же модель эмбеддингов
        2. Вычисляется косинусное сходство между вектором запроса и всеми документами в базе
        3. Возвращаются топ-K наиболее похожих документов
        
        Args:
            query: Поисковый запрос пользователя
            k: Количество результатов (по умолчанию из config)
            
        Returns:
            List[LangChainDocument]: Список найденных документов с метаданными
        """
        if self.vector_store is None:
            raise RuntimeError("Векторная база данных не инициализированна")
        
        if k is None :
            k = settings.search_top_k
            
        logging.info(f"Поиск по запросу: '{query}' (топ-{k})")

        results = self.vector_store.similarity_search(query, k)
        
        logging.info(f"Найденно документов: {len(results)}")
        return results
    
    def search_with_scores(self, query: str, k: int = None) -> List[tuple]:
        """
        Поиск с возвратом scores (косинусное сходство).
        
        Полезно для отладки и фильтрации по порогу релевантности.
        
        Returns:
            List[tuple[Document, float]]: Список кортежей (документ, score)
        """
        if self.vector_store is None:
            raise RuntimeError("Векторная база не инициализирована")
        
        if k is None:
            k = settings.search_top_k
        
        results = self.vector_store.similarity_search_with_score(query, k=k)
        return results      
    
if __name__ == "__main__":
    print("=" * 60)
    print("ТЕСТ ВЕКТОРНОЙ БАЗЫ ДАННЫХ")
    print("=" * 60)
    
    ingestor = DocumentIngestor()
    documents = ingestor.process()
    
    if not documents:
        print(" Документы не найдены !!!!")
        exit(1)
    
    # Создаём менеджер векторной базы
    manager = VectorStoreManager()
    vector_store = manager.create(documents)   # Создаём базу (первый запуск — медленно, ~2-4 минуты)
    
    print("\n" + "=" * 60)
    print("ТЕСТ ПОИСКА")
    print("=" * 60)
    
    test_queries = [
        "Какой протокол обмена используется между МКУ и УМИ?",
        "Как включить излучение шкафа 276ГГ02?",
        "Что такое сигнал PPS?"
    ]
    
    for query in test_queries:
        print(f"\n Запрос: '{query}'")
        results = manager.search(query, k=2)
        
        for i, doc in enumerate(results):
            print(f"   Результат #{i+1}:")
            print(f"   Файл: {doc.metadata.get('filename')}")
            print(f"   Текст: {doc.page_content[:150]}...")
            print()