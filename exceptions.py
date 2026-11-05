"""
exceptions.py
Кастомные исключения для RAG-системы.
Позволяют точно понимать, что пошло не так.
"""


class RAGBaseError(Exception):
    """Базовый класс для всех ошибок RAG-системы."""
    pass


class VectorStoreError(RAGBaseError):
    """Ошибка работы с векторной базой данных."""
    pass


class RetrieverError(RAGBaseError):
    """Ошибка поиска (vector/BM25/rerank)."""
    pass


class LLMError(RAGBaseError):
    """Ошибка взаимодействия с LLM (Ollama)."""
    pass


class AgentError(RAGBaseError):
    """Ошибка работы агента."""
    pass


class FileProcessingError(RAGBaseError):
    """Ошибка обработки файлов (PDF, DOCX и т.д.)."""
    pass


class ToolExecutionError(RAGBaseError):
    """Ошибка выполнения инструмента агента."""
    pass