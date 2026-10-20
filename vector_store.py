"""
Модуль для управления векторной базой данных ChromaDB с поддержкой Parent-Child Retrieval.
"""
from data_ingestion import DocumentIngestor   
import logging
from pathlib import Path
from typing import List, Optional
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document as LangChainDocument
# <-- ИСПРАВЛЕННЫЕ ИМПОРТЫ для LangChain >= 0.2.0
from langchain_community.retrievers import ParentDocumentRetriever
from langchain.storage import LocalFileStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from config import settings

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s : %(message)s')
    
class VectorStoreManager:
    def __init__(self): 
        logging.info(f"Загрузка модели эмбеддингов: {settings.embedder_model_name}")
        
        self.embeddings = HuggingFaceEmbeddings(
            model_name=settings.embedder_model_name,
            model_kwargs={
                'device': settings.embedder_device,
                'local_files_only': True
            },
            encode_kwargs={'normalize_embeddings': True},
        )
        
        # Родитель: большой чанк (2000-2500 символов), чтобы дать LLM полный контекст для развернутого ответа
        self.parent_splitter = RecursiveCharacterTextSplitter(
            chunk_size=2000, 
            chunk_overlap=200,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
        
        # Ребенок: маленький чанк (400-500 символов), для идеальной точности векторного поиска
        self.child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=400, 
            chunk_overlap=50,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
        
        # Оно будет сохранено в подпапке parent_docs внутри основной директории Chroma
        parent_store_path = Path(settings.chroma_persist_dir) / "parent_docs"
        self.docstore = LocalFileStore(str(parent_store_path))
        
        self.vector_store: Optional[Chroma] = None
        self.parent_retriever: Optional[ParentDocumentRetriever] = None
        
        logging.info("Модель эмбеддингов и сплиттеры инициализированы (оффлайн-режим).")
    
    def create(self, documents: List[LangChainDocument]) -> ParentDocumentRetriever:
        """
        Создание новой базы с использованием Parent-Child Retrieval.
        """
        logging.info(f"Создание векторной базы из {len(documents)} документов (Parent-Child режим)")
        persist_path = Path(settings.chroma_persist_dir)
        
        if persist_path.exists():
            logging.warning(f"Папка {persist_path} уже существует. База будет обновлена/перезаписана.")        
        
        # 1. Создаем пустой Chroma для хранения ТОЛЬКО маленьких чанков (детей)
        self.vector_store = Chroma(
            embedding_function=self.embeddings,
            persist_directory=str(persist_path),
            collection_name="PRL27_technical_docs_children" # <-- Отдельная коллекция для детей
        )
        
        # 2. Инициализируем ParentDocumentRetriever
        self.parent_retriever = ParentDocumentRetriever(
            vectorstore=self.vector_store,
            docstore=self.docstore,
            child_splitter=self.child_splitter,
            parent_splitter=self.parent_splitter,
        )
        
        # 3. Магия LangChain: add_documents сам разобьет документы на родителей и детей,
        # сохранит родителей в docstore, а детей (со ссылками на родителей) отправит в Chroma.
        self.parent_retriever.add_documents(documents)
        
        logging.info(f"Векторная база и хранилище родителей созданы в: {persist_path.absolute()}")
        return self.parent_retriever
    
    def load(self) -> ParentDocumentRetriever:
        """
        Загрузка существующей базы. LocalFileStore автоматически подгрузит сохраненных родителей.
        """ 
        persist_path = Path(settings.chroma_persist_dir)
        parent_store_path = persist_path / "parent_docs"
        
        if not persist_path.exists() or not parent_store_path.exists():
            raise FileNotFoundError(
                f"Векторная база или хранилище родителей не найдены по пути: {persist_path.absolute()}\n"
                f"Сначала создайте базу через метод create()"
            )
        
        logging.info(f"Загрузка векторной базы и хранилища родителей из: {persist_path.absolute()}")
        
        # 1. Загружаем Chroma с детьми
        self.vector_store = Chroma(
            persist_directory=str(persist_path),
            collection_name="PRL27_technical_docs_children",
            embedding_function=self.embeddings
        )
        
        # 2. Загружаем LocalFileStore с родителями (он читает файлы с диска автоматически)
        self.docstore = LocalFileStore(str(parent_store_path))
        
        # 3. Собираем ретривер заново
        self.parent_retriever = ParentDocumentRetriever(
            vectorstore=self.vector_store,
            docstore=self.docstore,
            child_splitter=self.child_splitter,
            parent_splitter=self.parent_splitter,
        )

        logging.info("Векторная база и родители загружены")
        return self.parent_retriever

    def search(self, query: str, k: int = None) -> List[LangChainDocument]:
        """
        Поиск с использованием Parent-Child логики.
        Ищет по маленьким чанкам, но возвращает БОЛЬШИЕ родительские чанки.
        """
        if self.parent_retriever is None:
            raise RuntimeError("Векторная база данных не инициализирована")
        
        if k is None:
            k = settings.search_top_k
            
        logging.info(f"Поиск по запросу: '{query}' (топ-{k} родителей)")

        # <-- ИЗМЕНЕНО: Используем invoke ретривера, он сам делает магию подстановки родителей
        results = self.parent_retriever.invoke(query, k=k)
        
        logging.info(f"Найдено документов (родителей): {len(results)}")
        return results
    
    def search_with_scores(self, query: str, k: int = None) -> List[tuple]:
        """
        ВНИМАНИЕ: ParentDocumentRetriever по умолчанию не возвращает scores напрямую 
        в удобном формате tuple, так как он агрегирует результаты. 
        Для отладки лучше использовать обычный vector_store.similarity_search_with_score,
        но помни, что это вернет детей, а не родителей.
        """
        if self.vector_store is None:
            raise RuntimeError("Векторная база не инициализирована")
        if k is None:
            k = settings.search_top_k
        
        return self.vector_store.similarity_search_with_score(query, k=k)
    
if __name__ == "__main__":
    print("=" * 60)
    print("ТЕСТ ВЕКТОРНОЙ БАЗЫ ДАННЫХ (PARENT-CHILD)")
    print("=" * 60)
    
    ingestor = DocumentIngestor()
    documents = ingestor.process()
    
    if not documents:
        print(" Документы не найдены !!!!")
        exit(1)
    
    manager = VectorStoreManager()
    
    # Создаем базу (первый запуск)
    retriever = manager.create(documents)
    
    print("\n" + "=" * 60)
    print("ТЕСТ ПОИСКА (Возвращаются большие родительские чанки!)")
    print("=" * 60)
    
    test_queries = [
        "Как включить излучение шкафа 276ГГ02?",
        "Что такое сигнал PPS?"
    ]
    
    for query in test_queries:
        print(f"\n Запрос: '{query}'")
        results = manager.search(query, k=2)
        
        for i, doc in enumerate(results):
            print(f"   Результат #{i+1}:")
            print(f"   Файл: {doc.metadata.get('filename')}")
            print(f"   Длина текста: {len(doc.page_content)} символов (должно быть ~2000)")
            print(f"   Текст:\n   {doc.page_content[:300]}...\n")