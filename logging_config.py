"""
logging_config.py
Единая настройка логирования для всего проекта.
"""
import logging
import sys
from pathlib import Path


def setup_logging(level: str = "INFO", log_file: str = "app.log"):
    """
    Настройка структурированного логирования.
    
    Args:
        level: Уровень логирования (DEBUG, INFO, WARNING, ERROR)
        log_file: Путь к файлу логов
    """
    # Формат логов
    log_format = "%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    # Создаем директорию для логов, если нужно
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Настраиваем корневой логгер
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=log_format,
        datefmt=date_format,
        handlers=[
            # Вывод в консоль
            logging.StreamHandler(sys.stdout),
            # Запись в файл
            logging.FileHandler(log_file, encoding='utf-8'),
        ]
    )
    
    # Уменьшаем шум от сторонних библиотек
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    
    logging.info("=" * 60)
    logging.info("Логирование инициализировано")
    logging.info(f"Уровень: {level}, Файл: {log_file}")
    logging.info("=" * 60)


def get_logger(name: str) -> logging.Logger:
    """Получить логгер для конкретного модуля."""
    return logging.getLogger(name)