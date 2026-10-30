"""
Модуль Smart RAG с Роутингом и Parent-Child Retrieval.
"""
import re 
import logging
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from config import settings
from vector_store import VectorStoreManager
from hybrid_retriever import HybridRetriever
from langchain_core.callbacks import BaseCallbackHandler

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s : %(message)s')

class TokenCollector(BaseCallbackHandler):
    def __init__(self):
        self.tokens = []
        
    def on_llm_new_token(self, token: str, **kwargs):
        self.tokens.append(token)
        
    def get_text(self):
        return "".join(self.tokens)

class SmartRAG:
    def __init__(self, model_name: str = "qwen2.5:14b"):
        print(f"[SmartRAG] Инициализация с моделью: {model_name}", flush=True)
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
            max_tokens=4096,
            streaming=True
        )
        
        # 4. Промпт для РОУТЕРА
        # 4. Промпт для РОУТЕРА (УЛУЧШЕННЫЙ v2)
        self.router_prompt = ChatPromptTemplate.from_messages([
            ("system", """Ты — BUTUZIK.AI, диспетчер технической поддержки авиационного оборудования.
Проанализируй вопрос и определи, где искать ответ.

ПРАВИЛА (приоритет по порядку):
1. **USERDOC** — если в вопросе есть:
   - Имя файла с расширением (.pdf, .docx, .txt, .md)
   - Слова: "мой файл", "прикрепленный документ", "в резюме", "загруженный документ"
   - Вопросы про личные документы, отчеты, резюме (не технические)
   
2. **SEARCH** — если вопрос касается:
   - Оборудования ПРЛ-27СМ (шкафы 276ГГ02, 276ЦЦ02, платы МКУ, УМИ, ПОИ)
   - Технических инструкций, протоколов, схем, кодов ошибок
   - Команд, параметров, алгоритмов работы оборудования
   
3. **CHAT** — всё остальное (приветствия, благодарности, общие вопросы)

Отвечай ТОЛЬКО одним словом: USERDOC, SEARCH или CHAT"""),
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
        3. **Источники**: НЕ пиши источники самостоятельно! НЕ добавляй строки вида "[Источник: ...]" и заголовок "Источник:" — система подставит их автоматически. Просто отвечай по сути контекста.
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
        
        # 6. Промпт для ОБЫЧНОГО ОБЩЕНИЯ (CHAT mode)
        self.chat_prompt = ChatPromptTemplate.from_messages([
            ("system", """Ты — дружелюбный, knowledgeable и ПОДРОБНЫЙ ассистент BUTUZIK.AI.
            
ИСТОРИЯ ДИАЛОГА:
{history}

ПРАВИЛА ФОРМИРОВАНИЯ ОТВЕТА:
1. **РАЗВЕРНУТОСТЬ**: Давай МАКСИМАЛЬНО подробные ответы (минимум 5-7 предложений, а для инструкций — 10+ предложений).
2. **СТРУКТУРА**: 
   - Начни с краткого резюме (1-2 предложения)
   - Затем детализированное объяснение
   - Если это инструкция — ОБЯЗАТЕЛЬНО пронумеруй шаги (1, 2, 3...)
   - Добавь предупреждения о безопасности, если тема того требует
3. **ПРИМЕРЫ**: Если уместно, приводи конкретные примеры.
4. **УЧИТЫВАЙ КОНТЕКСТ**: Если это уточнение к предыдущему вопросу, давай дополнительную информацию, а не повторяй предыдущий ответ.
5. **ЕСТЕСТВЕННОСТЬ**: Объясняй понятно, дружелюбно, но профессионально.
6. **НЕ УПОМИНАЙ** техническую документацию ПРЛ-27СМ, если тебя об этом прямо не просят."""),
            ("human", "{question}")
        ])
        self.last_sources = []

        # 7. Промпт для ОТВЕТОВ ПО ПРИКРЕПЛЁННЫМ ФАЙЛАМ
        self.file_prompt = ChatPromptTemplate.from_messages([
            ("system", """Ты — ассистент, анализирующий документ, который пользователь прикрепил к сообщению.

ПРАВИЛА:
1. Отвечай СТРОГО по содержимому прикреплённого файла. НЕ используй внешние знания.
2. СОПОСТАВЛЯЙ ОТВЕТ С ВОПРОСОМ:
   - Если спрашивают о документе ЦЕЛИКОМ ("что в файле?", "резюмируй", "опиши документ") — дай развёрнутый структурированный разбор всех разделов.
   - Если задан КОНКРЕТНЫЙ вопрос ("какие навыки?", "где он живёт?", "какой опыт работы?") — отвечай ТОЛЬКО на этот вопрос, приводя релевантные факты, цифры и имена из файла. НЕ пересказывай весь документ.
   - Если вопрос — уточнение к предыдущему (см. историю диалога) — учитывай контекст прошлых ответов и не повторяй их.
3. Передавай конкретику из файла: имена, даты, цифры, технологии, термины — не обобщай.
4. Используй Markdown: списки, подзаголовки, таблицы — где уместно.
5. Если в файле нет ответа — скажи об этом прямо.
6. НЕ пиши раздел "Источники" — система добавит их автоматически.

ИСТОРИЯ ДИАЛОГА (для понимания уточнений):
{history}

СОДЕРЖИМОЕ ПРИКРЕПЛЁННОГО ФАЙЛА:
{context}"""),
            ("human", "Вопрос пользователя: {question}")
        ])
   
    def route(self, question: str, chat_history: list = None) -> str:
        """Определяет интент с учётом истории диалога"""
        history_context = ""
        if chat_history and len(chat_history) > 0:
            # Берем последние 4 сообщения (2 пары вопрос-ответ)
            last_msgs = chat_history[-4:]
            history_context = "ПРЕДЫДУЩИЙ ДИАЛОГ:\n" + "\n".join([
                f"{'Пользователь' if m['role']=='user' else 'Ассистент'}: {m['content'][:400]}" 
                for m in last_msgs
            ]) + "\n"
        
        router_prompt = ChatPromptTemplate.from_messages([
            ("system", f"""Ты — BUTUZIK.AI, диспетчер технической поддержки.

{history_context}

ПРАВИЛА определения интента (приоритет по порядку):
1. **CHAT** — если:
   - Это приветствие, благодарность, общий бытовой вопрос.
   - Это **уточнение** к предыдущему ответу (слова: "подробнее", "как именно", "а можно ещё", "распиши"), И предыдущая тема НЕ была сугубо технической про ПРЛ-27СМ.
   - Вопрос НЕ содержит технических терминов ПРЛ-27СМ.
   
2. **SEARCH** — если:
   - Вопрос про оборудование ПРЛ-27СМ (шкафы, платы, протоколы, сигналы).
   - Это уточнение к предыдущему техническому ответу про ПРЛ-27СМ.
   
3. **USERDOC** — если вопрос про конкретный загруженный пользователем файл.

Отвечай ТОЛЬКО одним словом: USERDOC, SEARCH или CHAT"""),
            ("human", "Текущий вопрос пользователя: {question}")
        ])
        
        chain = router_prompt | self.llm
        response = chain.invoke({"question": question}).content.strip().upper()
        for intent in ("USERDOC", "SEARCH", "CHAT"):
            if intent in response:
                return intent
        return "CHAT"

    def rewrite_query(self, question: str) -> str:
        """Переформулирует человеческий вопрос в строгий технический поисковый запрос."""
        rewrite_prompt = ChatPromptTemplate.from_messages([
            ("system", """Ты — BUTUZIK.AI - Технический эксперт по авиационному оборудованию ПРЛ-27СМ.
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
        """Контекст из документов: сначала ищем в текущем чате, потом в глобальной базе."""
        try:
            from document_processor import retrieve_user_context
            
            # 1. Сначала ищем в документах текущего чата
            ctx = retrieve_user_context(question, k=4, chat_id=chat_id)
            if ctx:
                print(f"[SmartRAG] Найдено в чате {chat_id}: {len(ctx)} симв.", flush=True)
                return ctx
            
            # 2. Если не нашли, ищем в глобальной базе (chat_id="global")
            print(f"[SmartRAG] Ищем в глобальной базе знаний...", flush=True)
            ctx_global = retrieve_user_context(question, k=4, chat_id="global")
            if ctx_global:
                print(f"[SmartRAG] Найдено в глобальной базе: {len(ctx_global)} симв.", flush=True)
                return ctx_global
            
            print(f"[SmartRAG] Документы не найдены", flush=True)
            return ""
        except Exception as e:
            import traceback
            print(f"[SmartRAG] Ошибка поиска пользовательских документов:", flush=True)
            traceback.print_exc() # <-- Это покажет точную строку и текст ошибки
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
            
            # Фильтрация файлов-оглавлений
            filtered_docs = []
            for doc in unique_docs:
                filename = doc.metadata.get('filename', '').lower()
                if not any(pattern in filename for pattern in ['содержание', 'contents', 'оглавление']):
                    filtered_docs.append(doc)
            
            if filtered_docs:
                unique_docs = filtered_docs
            
            # >>> СБОР ИСТОЧНИКОВ — ТОЛЬКО ЗДЕСЬ, когда unique_docs уже наполнен! <<<
            real_sources = list(set(
                doc.metadata.get('filename', 'Неизвестный файл')
                for doc in unique_docs
            ))
            # Добавляем источники из пользовательских документов, если они участвуют
            if user_ctx:
                for s in re.findall(r'\[Источник:\s*([^\]]+)\]', user_ctx):
                    if s not in real_sources:
                        real_sources.append(s)
            
            self.last_sources = real_sources
            self.last_context = "\n\n---\n\n".join(
                f"[Источник: {doc.metadata.get('filename', 'Неизвестный файл')}]\n{doc.page_content}"
                for doc in unique_docs
            )
            print(f"[STREAM] Найдено документов: {len(unique_docs)}, источники: {real_sources}", flush=True)
            
            context = self.last_context
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

    def query_stream(self, question: str, chat_history: list = None, chat_id=None, on_token=None, cancel_flag=None, user_context=None, recent_file_context=None) -> str:
        print(f"\n[STREAM] Вопрос: '{question}'", flush=True)

        # Формируем текстовый контекст истории
        history_text = ""
        if chat_history and len(chat_history) > 0:
            last_msgs = chat_history[-4:]
            history_text = "\n".join([f"{'Пользователь' if m['role']=='user' else 'Ассистент'}: {m['content'][:500]}" for m in last_msgs])
        
        # 1. СНАЧАЛА определяем интент С УЧЁТОМ ИСТОРИИ
        intent = self.route(question, chat_history)
        print(f"[STREAM] Интент: {intent}", flush=True)
        
        def _generate_stream(chain, context, question, hist_text):
            full_response = ""
            prompt_input = {"context": context, "question": question, "history": hist_text}
            for chunk in chain.stream(prompt_input):
                if cancel_flag and cancel_flag.get("cancelled"):
                    print("[STREAM] Генерация прервана флагом отмены", flush=True)
                    break 
                if hasattr(chunk, 'content') and chunk.content:
                    full_response += chunk.content
                    if on_token:
                        on_token(full_response)
            return full_response
        
        # ПРИКРЕПЛЁННЫЕ ФАЙЛЫ — высший приоритет, БЕЗ подмешивания базы знаний
        if user_context:
            print(f"[STREAM] Контекст из прикреплённых файлов: {len(user_context)} симв. — используем ТОЛЬКО его", flush=True)
            
            # ВАЖНО: глобальную базу НЕ подключаем, чтобы модель не ушла в документацию ПРЛ
            combined_context = user_context
            
            real_sources = re.findall(r'\[Прикреплённый файл:\s*([^\]]+)\]', user_context)
            self.last_sources = real_sources
            self.last_context = combined_context
            
            # Используем специальный промпт для файлов (без персоны инженера ПРЛ)
            chain = self.file_prompt | self.llm
            full_response = _generate_stream(chain, combined_context, question, history_text)
            
            if cancel_flag and cancel_flag.get("cancelled"):
                return "[STREAM ОТМЕНЕН]", []
            
            print("[STREAM] Успешный ответ сформирован (по прикреплённому файлу).", flush=True)
            return f"[С поиском]:\n{full_response}", real_sources
        
        # 1. СНАЧАЛА определяем интент С УЧЁТОМ ИСТОРИИ (только если файлов нет)
        intent = self.route(question, chat_history)
        print(f"[STREAM] Интент: {intent}", flush=True)
        
        # УТОЧНЯЮЩИЙ вопрос по недавно прикреплённому файлу
        # НО ТОЛЬКО если вопрос НЕ про технические темы ПРЛ-27СМ
        if recent_file_context and intent in ("CHAT", "USERDOC"):
            # Ключевые маркеры, которые означают "это вопрос про базу ПРЛ, не про файл"
            prl_keywords = [
                # Технические темы ПРЛ-27СМ
                'ппс', 'pps', 'прл', 'мку', 'пои', 'уми', 'прд',
                '276гг', '276цц', 'д2хк', 'шкаф', 'излучение', 
                'протокол передачи', 'синхронизатор', 'юстировк', 'топопривязк',
                'сигнал pps', 'мезонин', 'dsp', 'плис', 'pci', 'srio',
                
                # Маркеры самоидентификации ассистента (НЕ по файлу!)
                'как тебя зовут', 'твое имя', 'твоё имя', 'кто ты', 
                'что ты такое', 'как твое имя', 'представься',
                'ты кто', 'ты робот', 'ты человек', 'ты ии', 'ты нейросеть',
                'твой создатель', 'кто тебя создал', 'ты украл',
                
                # Опасные темы (НЕ по файлу, идти в обычный CHAT)
                'вирус', 'троян', 'убийств', 'убить', 'яд', 'отрав',
                'взлом', 'хакер', 'hack', 'malware', 'exploit',
            ]
            question_lower = question.lower()
            has_prl_marker = any(kw in question_lower for kw in prl_keywords)
            
            if not has_prl_marker:
                print(f"[STREAM] Уточнение по файлу: использую сохранённый контекст ({len(recent_file_context)} симв.)", flush=True)
                
                real_sources = re.findall(r'\[Прикреплённый файл:\s*([^\]]+)\]', recent_file_context)
                self.last_sources = real_sources
                self.last_context = recent_file_context
                
                chain = self.file_prompt | self.llm
                full_response = _generate_stream(chain, recent_file_context, question, history_text)
                
                if cancel_flag and cancel_flag.get("cancelled"):
                    return "[STREAM ОТМЕНЕН]", []
                
                print("[STREAM] Успешный ответ сформирован (по сохранённому файлу).", flush=True)
                return f"[С поиском]:\n{full_response}", real_sources
            else:
                print(f"[STREAM] Вопрос содержит тех. маркеры ПРЛ — пропускаю сохранённый файл, иду в базу знаний", flush=True)
                # НЕ возвращаемся, а идём дальше по пайплайну (SEARCH или обычный CHAT)
        
        # 2. CHAT mode
        if intent == "CHAT":
            has_filename = re.search(r'[\w\-\s]+\.(?:pdf|docx|txt|md)', question, re.IGNORECASE)
            has_my_file = re.search(r'мой\s+файл|прикреплённ?ый\s+документ|загруженн?ый', question, re.IGNORECASE)
            
            if not (has_filename or has_my_file):
                chain = self.chat_prompt | self.llm
                result = _generate_stream(chain, "", question, history_text)
                self.last_sources = []
                return result, []
            
            user_ctx = self._get_user_context(question, chat_id)
            if user_ctx:
                chain = self.generator_prompt | self.llm
                result = _generate_stream(chain, user_ctx, question, history_text)
                self.last_sources = re.findall(r'\[Источник:\s*([^\]]+)\]', user_ctx)
                return f"[С поиском]:\n{result}", []  # Источники из user_ctx
            return "[Без поиска]: Не удалось найти указанный документ."

        # 3. USERDOC mode
        if intent == "USERDOC":
            user_ctx = self._get_user_context(question, chat_id)
            if user_ctx:
                chain = self.generator_prompt | self.llm
                result = _generate_stream(chain, user_ctx, question, history_text)
                self.last_sources = re.findall(r'\[Источник:\s*([^\]]+)\]', user_ctx)
                return f"[С поиском]:\n{result}", []  # Источники из user_ctx
            return "[Без поиска]: В этом чате нет загруженных документов."

        # 4. SEARCH mode
        print("[STREAM] Переформулирование запроса для улучшения поиска...", flush=True)
        search_query = self.rewrite_query(question)
        print(f"[STREAM] Технический запрос: '{search_query}'", flush=True)
        
        user_ctx = self._get_user_context(question, chat_id)
        
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            print(f"[STREAM] Запуск поиска (Попытка {attempt})...", flush=True)
            docs = self.retriever.search(search_query, k=5)
            
            # ДЕТАЛЬНАЯ ОТЛАДКА: что вернул retriever
            print(f"[STREAM] Retriever вернул {len(docs)} документов", flush=True)
            for i, doc in enumerate(docs):
                fname = doc.metadata.get('filename', '???')
                clen = len(doc.page_content) if doc.page_content else 0
                print(f"  [{i}] filename='{fname}', content_len={clen}", flush=True)
            
            # ДЕДУПЛИКАЦИЯ
            seen_texts = set()
            unique_docs = []
            for doc in docs:
                clean_text = " ".join(doc.page_content.split()) if doc.page_content else ""
                if clean_text and clean_text not in seen_texts:
                    seen_texts.add(clean_text)
                    unique_docs.append(doc)
            
            print(f"[STREAM] После дедупликации: {len(unique_docs)} документов", flush=True)
            
            # ФИЛЬТРАЦИЯ файлов-оглавлений
            filtered_docs = []
            for doc in unique_docs:
                filename = doc.metadata.get('filename', '').lower()
                if not any(pattern in filename for pattern in ['содержание', 'contents', 'оглавление']):
                    filtered_docs.append(doc)
            
            # Если после фильтрации ничего не осталось — используем оригинальные
            if filtered_docs:
                unique_docs = filtered_docs
            
            print(f"[STREAM] После фильтрации: {len(unique_docs)} документов", flush=True)
            
            # СОБИРАЕМ источники СНАЧАЛА (до формирования контекста!)
            real_sources = list(set(
                doc.metadata.get('filename', 'Неизвестный файл') 
                for doc in unique_docs
                if doc.metadata.get('filename')
            ))
            
            print(f"[STREAM] Реальные источники: {real_sources}", flush=True)
            
            # ФОРМИРУЕМ контекст
            context = "\n\n---\n\n".join([
                f"[Источник: {doc.metadata.get('filename', 'Неизвестный файл')}]\n{doc.page_content}"
                for doc in unique_docs
            ])
            
            if user_ctx:
                context = user_ctx + "\n\n---\n\n" + context
            
            # Сохраняем для fallback
            self.last_sources = real_sources
            self.last_context = context
            
            chain = self.generator_prompt | self.llm
            full_response = _generate_stream(chain, context, question, history_text)
            
            if cancel_flag and cancel_flag.get("cancelled"):
                return "[STREAM ОТМЕНЕН]", []
            
            answer_text = full_response.lower()
            negative_phrases = ["нет информации", "не указано", "не объясняется", "к сожалению", "не содержит", "отсутствует информация", "нет данных"]
            is_failure = any(phrase in answer_text for phrase in negative_phrases)
            
            if is_failure and attempt == 1 and not user_ctx:
                print("[STREAM] Self-RAG: Ответ не найден. Расширение поискового запроса...", flush=True)
                broad_query_prompt = ChatPromptTemplate.from_messages([
                    ("human", "Сделай этот поисковый запрос максимально широким и общим, оставив только ключевые технические термины и их синонимы: {query}")
                ])
                search_query = (broad_query_prompt | self.llm).invoke({"query": search_query}).content.strip()
                print(f"[STREAM] Расширенный запрос (Попытка 2): '{search_query}'", flush=True)
                continue
            
            print("[STREAM] Успешный ответ сформирован.", flush=True)
            print(f"[STREAM] ВОЗВРАЩАЕМ кортеж с источниками: {real_sources}", flush=True)
            return f"[С поиском]:\n{full_response}", real_sources
        
        return "[С поиском]:\nК сожалению, информация не найдена.", []
    
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