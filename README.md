# Aviation RAG System

Production-ready Retrieval-Augmented Generation (RAG) агент для работы с технической авиационной документацией (на примере оборудования ПРЛ-27СМ). 

Система спроектирована с учетом лучших практик MLOps: модульная архитектура, строгая типизация, гибридный поиск и локальный инференс для полной конфиденциальности данных.

## Архитектура пайплайна

```text
[Запрос пользователя] 
       ↓
[LLM Query Understanding] → Извлечение ключевых терминов
       ↓
[Hybrid Retriever] ────→ BM25 (лексический поиск) + Vector Search (семантический поиск)
       ↓                      ↓
[Cross-Encoder Reranker] ← Объединение через Reciprocal Rank Fusion (RRF)
       ↓
[Self-RAG Validation] → Оценка релевантности найденных чанков (Hallucination check)
       ↓
[Local LLM (Ollama)] → Генерация структурированного ответа с цитированием источников
```

## Ключевые особенности (Features)
- **100% Local & Private:** Инференс через Ollama, данные никогда не покидают локальную машину.
- **Hybrid Search:** Комбинация BM25 (для точных технических обозначений, например, "276ГГ02") и плотных векторов (для семантики).
- **Cross-Encoder Reranking:** Повышение точности выдачи за счет переоценки топ-документов моделью bge-reranker.
- **Self-RAG элементы:** Встроенная в промпт валидация на предмет галлюцинаций и соответствия контексту.
- **Production Architecture:** Модульный код, конфигурация через pydantic-settings, строгие type hints и разделение ответственности.

## Технологический стек
- **LLM Inference**: Ollama (Gemma 2 9B / Qwen 2.5 7B)
- **Orchestration**: LangChain
- **Vector Database**: ChromaDB
- **Embeddings**: intfloat/multilingual-e5-small
- **Data Processing**: PyPDF2, pdfplumber, python-docx, langchain_text_splitters
- **Config & Validation: pydantic-settings**

## Быстрый старт

1. Клонирование репозитория
```bash
git clone https://github.com/devfounder1/prod-aviation-rag-system.git
cd prod-aviation-rag-system
```

2. Настройка окружения
```bash
# Создание виртуального окружения
python -m venv venv
source venv/bin/activate  # Для Windows: venv\Scripts\activate

# Установка зависимостей
pip install -r requirements.txt
```

3. Установка и запуск Ollama
```bash
ollama pull gemma2:9b
ollama serve
```

4. Конфигурация
Скопируйте шаблон и заполните своими локальными путями:
```bash
cp .env.example .env
# Откройте .env и укажите путь к папке с вашими документами в DOCUMENTS_DIR
```

5. Запуск системы
```bash
python main.py
```

## Структура проекта

```text
.
├── .env.example          # Шаблон переменных окружения
├── .gitignore            # Правила игнорирования (секреты и данные исключены)
├── config.py             # Централизованная конфигурация (Pydantic V2)
├── data_ingestion.py     # Загрузка и чанкинг документов (PDF, DOCX, TXT)
├── vector_store.py       # Управление индексацией и поиском в ChromaDB
├── agent.py              # Логика RAG-агента, инструменты и Self-RAG промпты
├── main.py               # Точка входа (CLI интерфейс)
└── requirements.txt      # Зависимости проекта
```


