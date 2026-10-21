"""
Главный файл запуска интерактивного Smart RAG ассистента.
"""

import logging
from smart_rag import SmartRAG
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s : %(message)s')

def main():
    print("=" * 70)
    print("SMART RAG АССИСТЕНТ (Авиационное оборудование ПРЛ-27СМ)")
    print("=" * 70)
    print("Загрузка системы... (это может занять несколько секунд при первом запуске)")
    
    # Инициализация системы
    try:
        rag = SmartRAG()
        print("Система готова к работе!\n")
    except Exception as e:
        print(f"Ошибка инициализации: {e}")
        return

    print("Подсказки:")
    print("  - Задавайте вопросы по технической документации.")
    print("  - Система сама решит, нужен ли поиск по базе или можно ответить напрямую.")
    print("  - Введите 'выход' или 'exit' для завершения.\n")
    print("-" * 70)

    while True:
        try:
            # Запрос ввода от пользователя
            user_input = input("\n👤 Вы: ").strip()
            
            if not user_input:
                continue
                
            if user_input.lower() in ['выход', 'exit', 'quit']:
                print("\nДо свидания! Был рад помочь.")
                break
            
            # Получаем ответ от Smart RAG
            # чтобы пользователь видел "мысли" системы (Интент, Поиск)
            logging.getLogger().setLevel(logging.INFO)
            answer = rag.query(user_input)
            logging.getLogger().setLevel(logging.WARNING) # Возвращаем тихий режим
            
            print(f"\n{answer}")
            print("-" * 70)
            
        except KeyboardInterrupt:
            print("\n\nПринудительный выход. До свидания!")
            break
        except Exception as e:
            print(f"\nПроизошла непредвиденная ошибка: {e}")
            logging.error(f"Детали ошибки: {e}", exc_info=True)

if __name__ == "__main__":
    main()