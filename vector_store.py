"""
Модуль для управления векторной базой данных ChromaDB с надежной кастомной реализацией Parent-Child Retrieval.
"""
from data_ingestion import DocumentIngestor   
import logging
import uuid
import os
import json
from pathlib import Path
from typing import List, Optional
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document as LangChainDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter
from config import settings

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s : %(message)s')


# НАДЕЖНОЕ ХРАНИЛИЩЕ ДЛЯ РОДИТЕЛЕЙ (без зависимостей от langchain.storage)
class SimpleFileStore:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(self.path, exist_ok=True)

    def mset(self, key_value_pairs):
        """Сохраняет пары (ключ, значение) в отдельные JSON файлы"""
        for key, value in key_value_pairs:
            file_path = os.path.join(self.path, f"{key}.json")
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(value, f, ensure_ascii=False)

    def mget(self, keys):
        """Загружает значения по списку ключей"""
        results = []
        for key in keys:
            file_path = os.path.join(self.path, f"{key}.json")
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    results.append(json.load(f))
            else:
                results.append(None)
        return results

# МЕНЕДЖЕР ВЕКТОРНОЙ БАЗЫ
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
        
        # Сплиттер для РОДИТЕЛЕЙ
        self.parent_splitter = RecursiveCharacterTextSplitter(
            chunk_size=2000, 
            chunk_overlap=200,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
        
        # Сплиттер для ДЕТЕЙ
        self.child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=400, 
            chunk_overlap=50,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
        
        # Инициализация нашего надежного хранилища (ВСЕГДА SimpleFileStore, никаких dict!)
        parent_store_path = Path(settings.chroma_persist_dir) / "parent_docs"
        self.docstore = SimpleFileStore(str(parent_store_path))
        
        self.vector_store: Optional[Chroma] = None
        logging.info("Модель эмбеддингов, сплиттеры и хранилище инициализированы (оффлайн-режим).")
    
    def create(self, documents: List[LangChainDocument]) -> Chroma:
        logging.info(f"Создание векторной базы (Parent-Child режим) из {len(documents)} документов")
        persist_path = Path(settings.chroma_persist_dir)
        
        if persist_path.exists():
            logging.warning(f"Папка {persist_path} уже существует. База будет перезаписана.")        
        
        parent_docs = self.parent_splitter.split_documents(documents)
        child_docs = []
        
        for parent in parent_docs:
            parent_id = str(uuid.uuid4())
            self.docstore.mset([(parent_id, parent.page_content)])
            
            children = self.child_splitter.split_documents([parent])
            for child in children:
                child.metadata["parent_id"] = parent_id
                child.metadata["filename"] = parent.metadata.get("filename", "Unknown")
                child_docs.append(child)
                
        logging.info(f"Создано {len(parent_docs)} родителей и {len(child_docs)} детей.")
        
        self.vector_store = Chroma.from_documents(
            documents=child_docs,
            embedding=self.embeddings,
            persist_directory=str(persist_path),
            collection_name="PRL27_technical_docs_children"
        )
        
        logging.info(f"Векторная база и хранилище родителей созданы в: {persist_path.absolute()}")
        return self.vector_store
    
    def load(self) -> Chroma:
        persist_path = Path(settings.chroma_persist_dir)
        
        if not persist_path.exists():
            raise FileNotFoundError(
                f"Векторная база не найдена по пути: {persist_path.absolute()}\n"
                f"Сначала создайте базу через метод create()"
            )
        
        logging.info(f"Загрузка векторной базы из: {persist_path.absolute()}")
        
        self.vector_store = Chroma(
            persist_directory=str(persist_path),
            collection_name="PRL27_technical_docs_children",
            embedding_function=self.embeddings
        )
        
        # Пересоздаем хранилище родителей (оно автоматически увидит файлы на диске)
        parent_store_path = persist_path / "parent_docs"
        self.docstore = SimpleFileStore(str(parent_store_path)) # <-- ТОЛЬКО SimpleFileStore
            
        logging.info("Векторная база и хранилище родителей загружены")
        return self.vector_store

    def search(self, query: str, k: int = None) -> List[LangChainDocument]:
        if self.vector_store is None:
            raise RuntimeError("Векторная база данных не инициализирована")
        
        if k is None:
            k = settings.search_top_k
            
        logging.info(f"Поиск по запросу: '{query}' (топ-{k} родителей)")

        child_results = self.vector_store.similarity_search(query, k=k * 3)
        logging.info(f"DEBUG: Найдено детей в Chroma: {len(child_results)}")

        unique_parents = []
        seen_parent_ids = set()
        
        for child in child_results:
            parent_id = child.metadata.get("parent_id")
            logging.info(f"DEBUG: Проверяем ребенка, parent_id = {parent_id}")
            
            if parent_id and parent_id not in seen_parent_ids:
                seen_parent_ids.add(parent_id)
                
                parent_text_list = self.docstore.mget([parent_id])
                parent_text = parent_text_list[0] if parent_text_list else ""
                
                logging.info(f"DEBUG: Текст родителя получен: {bool(parent_text)} (длина: {len(parent_text) if parent_text else 0})")
                
                if parent_text:
                    unique_parents.append(LangChainDocument(
                        page_content=parent_text,
                        metadata={"filename": child.metadata.get("filename", "Unknown")}
                    ))
                    
                if len(unique_parents) >= k:
                    break
                    
        logging.info(f"Найдено уникальных документов (родителей): {len(unique_parents)}")
        return unique_parents

if __name__ == "__main__":
    print("=" * 60)
    print("ТЕСТ ВЕКТОРНОЙ БАЗЫ ДАННЫХ (CUSTOM PARENT-CHILD)")
    print("=" * 60)
    
    ingestor = DocumentIngestor()
    documents = ingestor.process()
    
    if not documents:
        print("Документы не найдены !!!!")
        exit(1)
    
    manager = VectorStoreManager()
    manager.create(documents)
    
    print("\n" + "=" * 60)
    print("ТЕСТ ПОИСКА (Возвращаются большие родительские чанки!)")
    print("=" * 60)
    
    test_queries = ["Как включить излучение шкафа 276ГГ02?", "Что такое сигнал PPS?"]
    
    for query in test_queries:
        print(f"\nЗапрос: '{query}'")
        results = manager.search(query, k=2)
        for i, doc in enumerate(results):
            print(f"   Результат #{i+1}: {doc.metadata.get('filename')} | {len(doc.page_content)} симв.")