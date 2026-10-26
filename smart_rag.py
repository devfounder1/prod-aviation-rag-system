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
Проанализируй вопрос и определи, где искать ответ.

ПРАВИЛА:
- Если вопрос про ЗАГРУЖЕННЫЙ пользователем файл/документ ("что в файле", "в документе, который я загрузил", "опиши содержимое документа", "а в файле ...") — ответь строго одним словом: USERDOC
- Если вопрос касается оборудования, шкафов (276ГГ02, 276ЦЦ02), плат (МКУ, УМИ, ПОИ), протоколов, инструкций, схем, кодов ошибок или технических терминов — ответь строго одним словом: SEARCH
- Если это приветствие, благодарность или вопрос не по теме — ответь строго одним словом: CHAT

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
        chain = self.router_prompt | self.llm
        response = chain.invoke({"question": question}).content.strip().upper()
        for intent in ("USERDOC", "SEARCH", "CHAT"):
            if intent in response:
                return intent
        return "CHAT"

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

    def _get_user_context(self, question: str, chat_id=None) -> str:
        """Контекст из документов, загруженных пользователем (кнопка '+')."""
        try:
            from document_processor import retrieve_user_context
            ctx = retrieve_user_context(question, k=4, chat_id=chat_id)
            if ctx:
                print(f"[SmartRAG] Контекст из пользовательских документов: {len(ctx)} симв.", flush=True)
            return ctx or ""
        except Exception as e:
            print(f"[SmartRAG] пользовательские документы недоступны: {e}", flush=True)
            return ""

    def query(self, question: str, chat_id=None) -> str:
        """Главный метод пайплайна: Self-RAG + приоритет пользовательских документов."""
        print(f"\nВопрос: '{question}'", flush=True)
        user_ctx = self._get_user_context(question, chat_id)
        
        # 0. Приоритетный контекст из загруженных пользователем документов
        user_ctx = self._get_user_context(question)
        
        intent = self.route(question)
        print(f"Интент модели: {intent}", flush=True)
        
        if intent == "USERDOC":
            if user_ctx:
                chain = self.generator_prompt | self.llm
                response = chain.invoke({"context": user_ctx, "question": question})
                return f"[С поиском]:\n{response.content}"
            return ("[Без поиска]: В этом чате нет загруженных документов. "
                    "Нажмите «+» рядом с полем ввода, чтобы прикрепить файл.")
        
        # CHAT без пользовательских документов — обычный ассистент
        if intent == "CHAT" and not user_ctx:
            chain = self.generator_prompt | self.llm
            response = chain.invoke({
                "context": "Контекст отсутствует. Отвечай как обычный вежливый ассистент.",
                "question": question})
            return f"[Без поиска]: {response.content}"
        
        # CHAT, но есть пользовательский документ (например «что в моём документе?»)
        if intent == "CHAT" and user_ctx:
            chain = self.generator_prompt | self.llm
            response = chain.invoke({"context": user_ctx, "question": question})
            return f"[С поиском]:\n{response.content}"
        
        # SEARCH-ветка с Self-RAG
        print("Переформулирование запроса для улучшения поиска...", flush=True)
        search_query = self.rewrite_query(question)
        print(f"Технический запрос для поиска (Попытка 1): '{search_query}'", flush=True)
        
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            print(f"Запуск поиска (Попытка {attempt})...", flush=True)
            docs = self.retriever.search(search_query, k=5)
            
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
            
            # Пользовательские документы идут ПЕРВЫМИ в контексте
            if user_ctx:
                context = user_ctx + "\n\n---\n\n" + context
            
            chain = self.generator_prompt | self.llm
            response = chain.invoke({"context": context, "question": question})
            answer_text = response.content.lower()
            
            negative_phrases = [
                "нет информации", "не указано", "не объясняется", "к сожалению",
                "не содержит", "отсутствует информация", "нет данных"
            ]
            is_failure = any(phrase in answer_text for phrase in negative_phrases)
            
            if is_failure and attempt == 1 and not user_ctx:
                print("Self-RAG: Ответ не найден. Автоматическое расширение поискового запроса...", flush=True)
                broad_query_prompt = ChatPromptTemplate.from_messages([
                    ("human", "Сделай этот поисковый запрос максимально широким и общим, оставив только ключевые технические термины и их синонимы: {query}")
                ])
                search_query = (broad_query_prompt | self.llm).invoke({"query": search_query}).content.strip()
                print(f"Расширенный технический запрос (Попытка 2): '{search_query}'", flush=True)
                continue
            
            print("Успешный ответ сформирован.", flush=True)
            return f"[С поиском]:\n{response.content}"
        
        return ("[С поиском]:\nК сожалению, даже после расширения поискового запроса, "
                "в предоставленной документации не найдено точной информации по вашему вопросу. "
                "Попробуйте переформулировать его или обратитесь к инженеру.")


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