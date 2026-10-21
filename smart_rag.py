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
    def __init__(self):
        # Инициализация векторной базы (Parent-Child)
        self.vs_manager = VectorStoreManager()
        self.vs_manager.load()
        
        # Инициализация ГИБРИДНОГО ретривера (BM25 + Vector + RRF + Reranker)
        self.retriever = HybridRetriever(self.vs_manager)
        
        # Инициализация LLM
        self.llm = ChatOpenAI(
            model=settings.llm_model_name,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            temperature=0.1,
            max_tokens=1024
        )
        
        # 4. Промпт для РОУТЕРА
        self.router_prompt = ChatPromptTemplate.from_messages([
            ("system", """Ты — диспетчер технической поддержки авиационного оборудования.
Проанализируй вопрос пользователя и определи, нужно ли искать ответ в технической базе знаний.

ПРАВИЛА:
- Если вопрос касается оборудования, шкафов (например, 276ГГ02, 276ЦЦ02), плат (МКУ, УМИ, ПОИ), протоколов, инструкций, схем, кодов ошибок или любых технических терминов — ответь строго одним словом: SEARCH
- Если это приветствие, благодарность, вопрос не по теме (погода, код на Python, общие фразы) — ответь строго одним словом: CHAT

Не пиши ничего кроме этого слова."""),
            ("human", "{question}")
        ])
        
        # 5. Промпт для ГЕНЕРАЦИИ развернутого и структурированного ответа
        self.generator_prompt = ChatPromptTemplate.from_messages([
            ("system", """Ты — старший инженер-наставник. Твоя задача — дать максимально полный и полезный ответ на основе предоставленного КОНТЕКСТА.

ПРАВИЛА ФОРМИРОВАНИЯ ОТВЕТА:
1. **Прямой ответ**: Начни с четкого ответа на основе фактов из текста.
2. **Частичная информация**: Если в тексте описывается действие (например, "МКУ опрашивает параметры" или "выдает сброс аварии"), но не приводится полный список параметров или точное название команды, **обязательно упомяни это**. Не пиши просто "не указано", а напиши: "В документе упоминается, что МКУ опрашивает параметры и выдает сброс аварии, однако конкретный перечень параметров/команд не детализирован".
3. **Детали из документа**: Используй все доступные условия и последовательности из контекста.
4. **Источник**: Всегда указывай источник информации в конце ответа в формате: `[Источник: имя_файла]`.
5. **Запрет на выдумки**: НИКОГДА не добавляй факты, названия параметров или команды, которых нет в тексте.

КОНТЕКСТ:
{context}"""),
            ("human", "Вопрос: {question}\nПодробный и структурированный ответ:")
        ])

    def route(self, question: str) -> str:
        """Определяет интент: SEARCH или CHAT"""
        chain = self.router_prompt | self.llm
        response = chain.invoke({"question": question}).content.strip().upper()
        return "SEARCH" if "SEARCH" in response else "CHAT"

    def query(self, question: str) -> str:
        """Главный метод пайплайна"""
        print(f"\nВопрос: '{question}'")
        
        intent = self.route(question)
        print(f"Интент модели: {intent}")
        
        if intent == "CHAT":
            chain = self.generator_prompt | self.llm
            response = chain.invoke({"context": "Контекст отсутствует. Отвечай как обычный вежливый ассистент.", "question": question})
            return f"[Без поиска]: {response.content}"
            
        else:
            print("Запуск гибридного Parent-Child поиска (BM25 + Vector + RRF)...")
            # увеличиваем k до 5, чтобы захватить больше контекста из родительских документов
            docs = self.retriever.search(question, k=5)
            
            # Жесткая дедупликация
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
            
            print("\n" + "=" * 60)
            print("DEBUG: ЧТО ИМЕННО ВИДИТ LLM (КОНТЕКСТ):")
            print(context)
            print("=" * 60 + "\n")
            
            chain = self.generator_prompt | self.llm
            response = chain.invoke({"context": context, "question": question})
            return f"[С поиском]:\n{response.content}"



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