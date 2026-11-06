"""
logging_config.py
Единая настройка логирования для всего проекта.
"""
import logging
import sys
from pathlib import Path

logging.getLogger("httpx2").setLevel(logging.WARNING)

def setup_logging(level: str = "INFO", log_file: str = "logs/app.log"):
    """Настройка структурированного логирования."""
    log_format = "%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding='utf-8'),
        ]
    )
    
    # УМЕНЬШАЕМ ШУМ от сторонних библиотек
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    
    # ОТКЛЮЧАЕМ спам от faster_whisper (wake-word listener)
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    
    # УБИРАЕМ шум от torch
    logging.getLogger("torch").setLevel(logging.WARNING)
    logging.getLogger("torch.distributed").setLevel(logging.ERROR)
    
    logging.info("=" * 60)
    logging.info("Логирование инициализировано")
    logging.info(f"Уровень: {level}, Файл: {log_file}")
    logging.info("=" * 60)


def get_logger(name: str) -> logging.Logger:
    """Получить логгер для конкретного модуля."""
    return logging.getLogger(name)