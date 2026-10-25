"""
Модуль Smart RAG с Роутингом и Parent-Child Retrieval.
"""

import logging
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from config import settings
from vector_store import VectorStoreManager
from hybrid_retriever import HybridRetriever

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s : %(message)s')

class SmartRAG:
    def __init__(self, model_name: str = "qwen2.5:14b"):
        print(f"[SmartRAG] 🔧 Инициализация с моделью: {model_name}", flush=True)
        self.model_name = model_name
        
        try:
            # ... твой существующий код инициализации ...
            print(f"[SmartRAG] Инициализация завершена успешно", flush=True)
        except Exception as e:
            print(f"[SmartRAG] Ошибка инициализации: {e}", flush=True)
            raise
        # Инициализация векторной базы (Parent-Child)
        self.vs_manager = VectorStoreManager()
        self.vs_manager.load()
        
        # Инициализация ГИБРИДНОГО ретривера (BM25 + Vector + RRF + Reranker)
        self.retriever = HybridRetriever(self.vs_manager)
        
        # Инициализация LLM
        self.llm = ChatOpenAI(
            model=self.model_name,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            temperature=0.1,
            max_tokens=1024
        )
        
        # 4. Промпт для РОУТЕРА
        self.router_prompt = ChatPromptTemplate.from_messages([
            ("system", """Ты — BUTUZIK.AI - диспетчер технической поддержки авиационного оборудования.
Проанализируй вопрос пользователя и определи, нужно ли искать ответ в технической базе знаний.

ПРАВИЛА:
- Если вопрос касается оборудования, шкафов (например, 276ГГ02, 276ЦЦ02), плат (МКУ, УМИ, ПОИ), протоколов, инструкций, схем, кодов ошибок или любых технических терминов — ответь строго одним словом: SEARCH
- Если это приветствие, благодарность, вопрос не по теме (погода, код на Python, общие фразы) — ответь строго одним словом: CHAT

Не пиши ничего кроме этого слова."""),
            ("human", "{question}")
        ])
        
        # 5. Промпт для ГЕНЕРАЦИИ ответа (с логикой инженера-диагноста)
        self.generator_prompt = ChatPromptTemplate.from_messages([
            ("system", """Ты — старший инженер-диагност по оборудованию ПРЛ-27СМ с многолетним опытом.

        ПРАВИЛА ФОРМИРОВАНИЯ ОТВЕТА:
        1. **Развернутость**: Давай подробные, структурированные ответы. Используй абзацы, списки, выделения.
        2. **Таблицы**: Если в контексте есть табличные данные или пользователь просит таблицу — ОБЯЗАТЕЛЬНО форматируй их в Markdown:
        | Колонка 1 | Колонка 2 | Колонка 3 |
        |-----------|-----------|-----------|
        | Данные 1  | Данные 2  | Данные 3  |
        3. **Источники**: Всегда указывай источник в конце: [Источник: имя_файла]
        4. **Честность**: Если информации недостаточно — скажи об этом, но предоставь всё, что есть.
        5. **Технические детали**: Не упрощай технические термины. Инженеры ценят точность.

        Формат ответа:
        - Начни с краткого резюме (1-2 предложения)
        - Затем детализированное объяснение
        - Если есть шаги — пронумеруй их
        - Если есть параметры/коды — оформи в таблицу
        - В конце укажи источник

        КОНТЕКСТ:
        {context}"""),
            ("human", "Вопрос: {question}\nРазвернутый технический ответ:")
        ])

    def route(self, question: str) -> str:
        """Определяет интент: SEARCH или CHAT"""
        chain = self.router_prompt | self.llm
        response = chain.invoke({"question": question}).content.strip().upper()
        return "SEARCH" if "SEARCH" in response else "CHAT"

    def rewrite_query(self, question: str) -> str:
        """Переформулирует человеческий вопрос в строгий технический поисковый запрос."""
        rewrite_prompt = ChatPromptTemplate.from_messages([
            ("system", """Ты — BUTUZIK.AI - Bтехнический эксперт по авиационному оборудованию ПРЛ-27СМ.
    Твоя задача — переформулировать вопрос пользователя в строгий технический поисковый запрос для системы RAG.

    ПРАВИЛА:
    1. Добавь технические синонимы и аббревиатуры (МКУ, УМИ, Д2ХК511, 276ГГ02, 276ЦЦ02, ПРД, ПРЛ-27СМ).
    2. Если вопрос про "выключить", добавь также "отключить", "прекратить".
    3. Если вопрос про "включить", добавь также "активировать", "запустить".
    4. НЕ отвечай на вопрос! Только перепиши его для поиска.
    
    Примеры:
    - "как выключить излучение?" → "отключение излучения ПРД, команда отключить Д2ХК511, прекращение выдачи СВЧ мощности"
    - "почему не горит лампочка?" → "отсутствие индикации, состояние индикаторов УМИ, причины отсутствия свечения"

    Вопрос пользователя: {question}
    Технический поисковый запрос:"""),
            ("human", "{question}")
        ])
        
        chain = rewrite_prompt | self.llm
        rewritten = chain.invoke({"question": question}).content.strip()
        return rewritten
    
    def query(self, question: str) -> str:
        """Главный метод пайплайна с поддержкой Self-RAG (авто-повтор при неудаче)."""
        print(f"\nВопрос: '{question}'")
        
        intent = self.route(question)
        print(f"Интент модели: {intent}")
        
        if intent == "CHAT":
            chain = self.generator_prompt | self.llm
            response = chain.invoke({"context": "Контекст отсутствует. Отвечай как обычный вежливый ассистент.", "question": question})
            return f"[Без поиска]: {response.content}"
            
        else:
            # Переформулируем запрос пользователя в технический
            print("Переформулирование запроса для улучшения поиска...")
            search_query = self.rewrite_query(question)
            print(f"Технический запрос для поиска (Попытка 1): '{search_query}'")
            
            # Цикл Self-RAG (максимум 2 попытки)
            max_attempts = 2
            for attempt in range(1, max_attempts + 1):
                print(f"Запуск поиска (Попытка {attempt})...")
                docs = self.retriever.search(search_query, k=5)
                
                # Дедупликация
                seen_texts = set()
                unique_docs = []
                for doc in docs:
                    clean_text = " ".join(doc.page_content.split())
                    if clean_text not in seen_texts:
                        seen_texts.add(clean_text)
                        unique_docs.append(doc)
                
                context = "\n\n---\n\n".join([
                    f"[Источник: {doc.metadata.get('filename', 'Неизвестный файл')}]\n{doc.page_content}" 
                    for doc in unique_docs
                ])
                
                # Генерация ответа
                chain = self.generator_prompt | self.llm
                response = chain.invoke({"context": context, "question": question})
                answer_text = response.content.lower()
                
                # Если модель говорит, что информации нет, и это ПЕРВАЯ попытка -> пробуем снова с более широким запросом
                # Self-RAG Critique (Проверка качества ответа)
                negative_phrases = [
                    "нет информации", 
                    "не указано", 
                    "не объясняется", 
                    "к сожалению", 
                    "не содержит",
                    "отсутствует информация",
                    "нет данных"
                ]
                is_failure = any(phrase in answer_text for phrase in negative_phrases)

                if is_failure and attempt == 1:
                    print("Self-RAG: Ответ не найден. Автоматическое расширение поискового запроса...")
                    # Делаем запрос максимально широким
                    broad_query_prompt = ChatPromptTemplate.from_messages([
                        ("human", "Сделай этот поисковый запрос максимально широким и общим, оставив только ключевые технические термины и их синонимы: {query}")
                    ])
                    search_query = (broad_query_prompt | self.llm).invoke({"query": search_query}).content.strip()
                    print(f"Расширенный технический запрос (Попытка 2): '{search_query}'")
                    continue
                
                # Если ответ найден (или это уже вторая попытка), возвращаем его
                print("Успешный ответ сформирован.")
                return f"[С поиском]:\n{response.content}"
            
            # Если обе попытки не дали хорошего результата
            return f"[С поиском]:\nК сожалению, даже после расширения поискового запроса, в предоставленной документации не найдено точной информации по вашему вопросу. Попробуйте переформулировать его или обратитесь к инженеру."


# ИНТЕРАКТИВНЫЙ ЗАПУСК
if __name__ == "__main__":
    print("=" * 70)
    print("SMART RAG АССИСТЕНТ (Parent-Child Retrieval)")
    print("=" * 70)
    print("Загрузка системы...")
    
    try:
        rag = SmartRAG()
        print("Система готова к работе!\n")
    except Exception as e:
        print(f"Ошибка инициализации: {e}")
        exit(1)

    print("Введите 'выход' или 'exit' для завершения.\n" + "-" * 70)

    while True:
        try:
            user_input = input("\nВы: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ['выход', 'exit', 'quit']:
                print("\nДо свидания!")
                break
            
            answer = rag.query(user_input)
            print(f"\n{answer}")
            print("-" * 70)
            
        except KeyboardInterrupt:
            print("\n\nПринудительный выход. До свидания!")
            break
        except Exception as e:
            print(f"\nОшибка: {e}")