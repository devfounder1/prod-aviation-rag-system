"""Bounded local logs. Record operational metadata, never document contents."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys


def rotating_handler(path: Path, max_bytes: int = 2_000_000,
                     backup_count: int = 3) -> RotatingFileHandler:
    path.parent.mkdir(parents=True, exist_ok=True)
    return RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8')


def setup_logging(level: str = 'INFO', log_file: str = 'logs/app.log') -> None:
    handler = rotating_handler(Path(log_file))
    logging.basicConfig(level=getattr(logging, level.upper()),
                        format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout), handler], force=True)
    for name in ('httpx', 'httpx2', 'httpcore', 'urllib3', 'chromadb', 'sentence_transformers',
                 'faster_whisper', 'torch'):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
