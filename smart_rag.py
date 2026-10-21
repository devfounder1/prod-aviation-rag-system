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
        # 5. Промпт для ГЕНЕРАЦИИ ответа (с логикой инженера-диагноста)
        self.generator_prompt = ChatPromptTemplate.from_messages([
            ("system", """Ты — старший инженер-диагност по оборудованию ПРЛ-27СМ. Твоя задача — дать максимально полезный ответ на основе КОНТЕКСТА.

ПРАВИЛА ДИАГНОСТИКИ:
1. **Анализ негативных вопросов**: Если пользователь спрашивает, почему чего-то НЕТ (например, "не горит индикатор", "не работает"), найди в тексте условия, при которых это ДОЛЖНО происходить. 
2. **Формулировка через проверку условий**: Вместо "в документе не сказано почему не работает", ответь так: "Согласно документации, [индикатор горит желтым, если выполнено условие X]. Если этого не происходит, проверьте: 1) условие X, 2) условие Y".
3. **Используй все детали**: Упоминай конкретные команды, состояния (например, "Отключено", "Включено") и сигналы ("Бланк ПРД"), указанные в тексте.
4. **Честность**: Если в тексте действительно нет никаких упоминаний об этом узле, состоянии или команде, честно скажи: "В предоставленных фрагментах нет информации о данной ситуации".
5. **Источник**: Всегда указывай источник в конце: [Источник: имя_файла].
6. **Запрет на выдумки**: НИКОГДА не придумывай причины неисправностей или параметры, которых нет в тексте.

КОНТЕКСТ:
{context}"""),
            ("human", "Вопрос: {question}\nДиагностический ответ:")
        ])

    def route(self, question: str) -> str:
        """Определяет интент: SEARCH или CHAT"""
        chain = self.router_prompt | self.llm
        response = chain.invoke({"question": question}).content.strip().upper()
        return "SEARCH" if "SEARCH" in response else "CHAT"

    def rewrite_query(self, question: str) -> str:
        """Переформулирует человеческий вопрос в строгий технический поисковый запрос."""
        rewrite_prompt = ChatPromptTemplate.from_messages([
            ("system", """Ты — технический эксперт по авиационному оборудованию ПРЛ-27СМ.
Твоя задача — переформулировать вопрос пользователя в строгий технический поисковый запрос для системы RAG.
Добавь технические синонимы, аббревиатуры (МКУ, УМИ, Д2ХК511, 276ГГ02, 276ЦЦ02, ПРД) и ключевые термины из предметной области.
НЕ отвечай на вопрос! Только перепиши его для поиска в виде набора ключевых слов и фраз.

Пример:
Вопрос пользователя: "почему не горит желтый на УМИ?"
Технический запрос: "отсутствие желтой индикации на УМИ, состояние индикаторов УМИ после команды Включить Д2ХК511, причины отсутствия индикации"""),
            ("human", "Вопрос пользователя: {question}\nТехнический поисковый запрос:")
        ])
        
        chain = rewrite_prompt | self.llm
        rewritten = chain.invoke({"question": question}).content.strip()
        return rewritten
    
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
            # Переформулируем запрос пользователя в технический
            print("Переформулирование запроса для улучшения поиска...")
            search_query = self.rewrite_query(question)
            print(f"Технический запрос для поиска: '{search_query}'")
            
            print("Запуск гибридного Parent-Child поиска (BM25 + Vector + RRF)...")
            
            # Ищем уже по переформулированному, "обогащенному" запросу!
            docs = self.retriever.search(search_query, k=5)
            
            # Жесткая дедупликация (оставляем как было)
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
            
            # Генерируем ответ на основе найденного контекста и ОРИГИНАЛЬНОГО вопроса пользователя
            chain = self.generator_prompt | self.llm
            response = chain.invoke({"context": context, "question": question}) # <-- Важно: передаем original question!
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