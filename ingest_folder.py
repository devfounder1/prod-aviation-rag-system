import sys
from pathlib import Path

# Гарантируем, что мы можем импортировать модули из корневой папки
sys.path.append(str(Path(__file__).parent))

try:
    from document_processor import add_document
except ImportError:
    print("Ошибка: не удалось импортировать document_processor. Убедитесь, что вы в корневой папке проекта.")
    sys.exit(1)

def ingest_folder(folder_path: str, chat_id: str = "global"):
    """Сканирует папку и добавляет все поддерживаемые файлы в векторную БД"""
    supported_extensions = {'.pdf', '.docx', '.txt', '.md', '.csv', '.xlsx'}
    folder = Path(folder_path)

    if not folder.exists() or not folder.is_dir():
        print(f"Папка '{folder_path}' не найдена или не является директорией!")
        return {"success": 0, "failed": 0, "total": 0, "category": ""}
    
    # Категория по умолчанию = имя папки
    category = folder.name
    
    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in supported_extensions]
    total = len(files)
    print(f"Найдено {total} файлов для обработки в категории '{category}'")
    
    if total == 0:
        print("Поддерживаемые файлы не найдены.")
        return {"success": 0, "failed": 0, "total": 0, "category": category}
    
    success_count = 0
    failed_count = 0
    
    for idx, file_path in enumerate(files, 1):
        print(f"[{idx}/{total}] Обработка: {file_path.name}...", end=" ", flush=True)
        try:
            # Передаем category, progress=lambda x: None чтобы не спамить в консоль при массовом импорте
            info = add_document(str(file_path), chat_id=chat_id, category=category, progress=lambda x: None)
            print(f"Успешно ({info['chunks']} чанков)")
            success_count += 1
        except Exception as e:
            print(f"Ошибка: {e}")
            failed_count += 1
            
    print(f"\nИмпорт завершен! Успешно: {success_count}, Ошибок: {failed_count}")
    return {"success": success_count, "failed": failed_count, "total": total, "category": category}

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Импорт документов из папки в RAG базу знаний")
    parser.add_argument("folder", nargs="?", default="./knowledge_base", help="Путь к папке с документами")
    args = parser.parse_args()
    
    ingest_folder(args.folder)