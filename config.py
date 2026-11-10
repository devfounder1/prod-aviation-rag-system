"""
Модуль конфигурации для RAG-системы.
Использует pydantic-settings для автоматической загрузки переменных из .env файла.
"""

import os
from pathlib import Path

# Offline runtime policy applies even if the shell has tracing enabled.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

from urllib.parse import urlsplit
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Класс настроек приложения.
    Pydantic автоматически читает переменные из .env, валидирует типы 
    и устанавливает значения по умолчанию.
    """
    
    # ==========================================
    # ПУТИ К ФАЙЛАМ
    # ==========================================
    documents_dir: str = "./documents_ae"
    chroma_persist_dir: str = str(Path(__file__).parent / "data" / "chroma")
    legacy_chroma_dir: str = str(Path(__file__).parent / "chroma_db_prl27")
    knowledge_collection: str = "knowledge_base"
    knowledge_base_path: str = "" 
    # ==========================================
    # НАСТРОЙКИ LLM (ЯЗЫКОВАЯ МОДЕЛЬ)
    # ==========================================
    llm_model_name: str = "qwen2.5:14b"
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_api_key: str = "ollama"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 2048
    vision_model_name: str = "qwen2.5vl:7b"
    vision_max_tokens: int = Field(default=512, ge=64, le=2048)
    
    # ==========================================
    # НАСТРОЙКИ EMBEDDINGS (ВЕКТОРИЗАЦИЯ)
    # ==========================================
    embedder_model_name: str = "intfloat/multilingual-e5-small"
    embedder_device: str = "mps"
    
    # ==========================================
    # НАСТРОЙКИ ПОИСКА
    # ==========================================
    search_top_k: int = 10
    rerank_top_k: int = 3
    chunk_size: int = 1000
    chunk_overlap: int = 200
    
    # ==========================================
    # НАСТРОЙКИ SELF-RAG
    # ==========================================
    relevance_threshold: float = 0.5
    
    # ==========================================
    # НАСТРОЙКИ ПОЛЬЗОВАТЕЛЬСКИХ ДОКУМЕНТОВ
    # ==========================================
    user_docs_collection: str = "attachments"
    user_docs_max_docs: int = 10
    user_docs_top_k: int = 4
    user_docs_chunk_size: int = 800
    user_docs_chunk_overlap: int = 150
    
    @field_validator("llm_base_url")
    @classmethod
    def local_endpoint(cls, value: str) -> str:
        parts = urlsplit(value)
        if (parts.scheme != "http" or parts.hostname != "127.0.0.1"
                or parts.port != 11434 or parts.path.rstrip("/") != "/v1"
                or parts.username or parts.password or parts.query or parts.fragment):
            raise ValueError("LLM must use http://127.0.0.1:11434/v1")
        return value.rstrip("/")

    # ==========================================
    # КОНФИГУРАЦИЯ PYDANTIC V2
    # ==========================================
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        validate_assignment=True
    )
    
    


# Создаем глобальный экземпляр настроек
settings = Settings()


# ==========================================
# БЫСТРАЯ ПРОВЕРКА КОНФИГУРАЦИИ
# ==========================================
if __name__ == "__main__":
    print("=" * 60)
    print("ПРОВЕРКА КОНФИГУРАЦИИ")
    print("=" * 60)
    
    # Проверяем, существует ли папка с документами
    docs_path = Path(settings.documents_dir)
    
    if docs_path.exists():
        print(f"   Папка документов найдена: {docs_path.absolute()}")
        # Считаем именно файлы, игнорируя сами папки при подсчете
        file_count = len([f for f in docs_path.rglob('*') if f.is_file()])
        print(f"   Количество файлов: {file_count}")
    else:
        print(f"   Папка документов НЕ найдена: {docs_path.absolute()}")
        print(f"   Создайте папку или измените DOCUMENTS_DIR в .env")
    
    print(f"\n Параметры:")
    print(f"   Модель LLM: {settings.llm_model_name}")
    print(f"   URL LLM: {settings.llm_base_url}")
    print(f"   Модель эмбеддингов: {settings.embedder_model_name}")
    print(f"   Устройство: {settings.embedder_device}")
    print(f"   Размер чанка: {settings.chunk_size}")
    print(f"   Перекрытие: {settings.chunk_overlap}")
    print("=" * 60)