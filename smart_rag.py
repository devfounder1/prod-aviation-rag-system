from config import settings
from vector_store import VectorStoreManager
from hybrid_retriever import HybridRetriever
import re
import logging
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s : %(message)s')

class SmartRAG:
    def __init__(self):
        # Инициализация поиска
        self.vs_manager = VectorStoreManager()
        self.vs_manager.load()
        self.retriever = HybridRetriever(self.vs_manager)
        
        # Инициализация LLM
        self.llm = ChatOpenAI(
            model = settings.llm_model_name,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.0,
            max_tokens = 10
        )
        
        # Промпт для Маршрутизатора
        # Мы заставляем модель выбрать строго одно из двух слов.
        self.router_prompt = ChatPromptTemplate.from_messages([
            ("system", """Ты — диспетчер технической поддержки авиационного оборудования.
Проанализируй вопрос пользователя и определи, нужно ли искать ответ в технической базе знаний.

ПРАВИЛА:
- Если вопрос касается оборудования, шкафов (например, 276ГГ02, 276ЦЦ02), плат (МКУ, УМИ, ПОИ), протоколов, инструкций, схем, кодов ошибок или любых технических терминов — ответь строго одним словом: SEARCH
- Если это приветствие, благодарность, вопрос не по теме (погода, код на Python, общие фразы) — ответь строго одним словом: CHAT

Не пиши ничего кроме этого слова."""),
            ("human", "{question}")
        ])
        
        self.generator_prompt = ChatPromptTemplate.from_messages([
            ("system", """Ты — технический ассистент. Отвечай СТРОГО на основе предоставленного контекста.
            
ПРАВИЛА:
1. Внимательно проанализируй все предоставленные фрагменты.
2. Если в контексте есть частичная или полная информация по вопросу, дай максимально подробный ответ и ОБЯЗАТЕЛЬНО укажи имена файлов-источников.
3. Если в контексте действительно НЕТ никакой полезной информации по сути вопроса, честно скажи: "В предоставленных фрагментах документации нет пошаговой инструкции или ответа на этот вопрос".
4. Не выдумывай факты. Отвечай на русском языке, используя профессиональную терминологию.

Контекст:
{context}"""),
            ("human", "{question}")
        ])
        
    def route(self, question: str) -> str:
        """Определяет интент: SEARCH или CHAT"""
        chain = self.router_prompt | self.llm
        response = chain.invoke({"question" : question}).content.strip().upper()
            
            # Очищаем ответ от возможных лишних символов, которые любит выдавать локальная модель
        if "SEARCH" in response:
            return "SEARCH"
        return "CHAT"
    
    def query(self, question: str) -> str:
        """Главный метод пайплайна"""
        print(f"\nВопрос: '{question}'")
        
        # ШАГ 1: Роутинг
        intent = self.route(question)
        print(f"Интент модели: {intent}")
        
        if intent == "CHAT":
            chain = self.generator_prompt | self.llm
            response = chain.invoke({"context": "Контекст отсутствует. Отвечай как обычный ассистент.", "question": question})
            return f"[Без поиска]: {response.content}"
            
        else:
            # ШАГ 2: Гибридный поиск. 
            # k=3 — оптимально для локальных моделей, чтобы не терять фокус внимания.
            print("Запуск гибридного поиска...")
            docs = self.retriever.search(question, k=3)
            
            # Форматируем документы
            context = "\n\n---\n\n".join([
                f"[Источник: {doc.metadata.get('filename')}]\n{doc.page_content}" 
                for doc in docs
            ])
            
            # ШАГ 3: Улучшенный промпт с Chain of Thought (CoT)
            smart_prompt = ChatPromptTemplate.from_messages([
                ("system", """Ты — технический ассистент. Твоя задача — найти ответ на вопрос пользователя в предоставленном КОНТЕКСТЕ.

ИНСТРУКЦИЯ:
1. Внимательно прочитай КОНТЕКСТ ниже.
2. Найди в нем предложения, которые напрямую отвечают на вопрос.
3. Сформулируй четкий, структурированный ответ на основе найденного. ОБЯЗАТЕЛЬНО укажи [Источник: имя_файла].
4. Если в КОНТЕКСТЕ действительно нет ни одного предложения, относящегося к сути вопроса, ответь: "В предоставленных фрагментах нет информации по этому вопросу". Не выдумывай факты.

КОНТЕКСТ:
{context}"""),
                # Формат "Вопрос/Ответ" работает как мощный триггер для локальных моделей (Gemma/Qwen)
                ("human", "Вопрос: {question}\nОтвет:")
            ])
            
            chain = smart_prompt | self.llm
            response = chain.invoke({"context": context, "question": question})
            return f"[С поиском]: {response.content}"
        
# ==========================================
# ТЕСТ
# ==========================================
if __name__ == "__main__":
    rag = SmartRAG()
    
    questions = [
        "Привет! Как дела?", # Должен сработать CHAT
        "Как включить излучение шкафа 276ГГ02?", # Должен сработать SEARCH
        "Напиши мне скрипт на Python для сортировки массива", # Должен сработать CHAT (не по теме)
        "Что говорится про сигнал PPS?" # Должен сработать SEARCH
    ]
    
    for q in questions:
        answer = rag.query(q)
        print(answer)
        print("=" * 60)