import os
from pathlib import Path
from document_processor import add_document # Твоя существующая функция

def ingest_folder(folder_path: str, category: str = "general"):
    """Сканирует папку и добавляет все поддерживаемые файлы в векторную БД"""
    supported_extensions = {'.pdf', '.docx', '.txt', '.md', '.csv', '.xlsx'}
    folder = Path(folder_path)
    
    if not folder.exists():
        print(f"Папка {folder_path} не найдена!")
        return
    
    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in supported_extensions]
    print(f"Найдено {len(files)} файлов для обработки в {folder_path}")
    
    for file_path in files:
        print(f"Обработка: {file_path.name}...")
        try:
            # Используем твою существующую логику, но передаем category в метаданные
            info = add_document(str(file_path), chat_id="global", category=category)
            print(f"Успешно: {info['filename']} ({info['chunks']} чанков)")
        except Exception as e:
            print(f"Ошибка при обработке {file_path.name}: {e}")
            
    print("🎉 Импорт завершен!")