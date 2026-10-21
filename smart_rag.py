"""
Модуль Smart RAG с Роутингом и Parent-Child Retrieval.
"""

import logging
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from config import settings
from vector_store import VectorStoreManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s : %(message)s')

class SmartRAG:
    def __init__(self):
        # 1. Инициализация поиска (теперь он использует Parent-Child под капотом!)
        self.vs_manager = VectorStoreManager()
        self.vs_manager.load() # Загружаем готовую базу с родителями и детьми
        
        # 2. Инициализация LLM
        self.llm = ChatOpenAI(
            model=settings.llm_model_name,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            temperature=0.1, # Чуть подняли для более связных ответов, но оставили низко для фактов
            max_tokens=1024
        )
        
        # 3. Промпт для РОУТЕРА (Маршрутизатора)
        self.router_prompt = ChatPromptTemplate.from_messages([
            ("system", """Ты — диспетчер технической поддержки авиационного оборудования.
Проанализируй вопрос пользователя и определи, нужно ли искать ответ в технической базе знаний.

ПРАВИЛА:
- Если вопрос касается оборудования, шкафов (например, 276ГГ02, 276ЦЦ02), плат (МКУ, УМИ, ПОИ), протоколов, инструкций, схем, кодов ошибок или любых технических терминов — ответь строго одним словом: SEARCH
- Если это приветствие, благодарность, вопрос не по теме (погода, код на Python, общие фrazы) — ответь строго одним словом: CHAT

Не пиши ничего кроме этого слова."""),
            ("human", "{question}")
        ])
        
        # 4. Промпт для ГЕНЕРАЦИИ ответа (супер-развернутый, благодаря Parent-Child)
        self.generator_prompt = ChatPromptTemplate.from_messages([
            ("system", """Ты — высококвалифицированный технический ассистент. Твоя задача — дать максимально полный и развернутый ответ на основе предоставленного КОНТЕКСТА.

ПРАВИЛА:
1. Внимательно изучи КОНТЕКСТ. В нем содержатся полные разделы документов, используй эту информацию для детального ответа.
2. Структурируй ответ: используй маркированные списки, жирный шрифт для ключевых терминов.
3. ОБЯЗАТЕЛЬНО указывай источники в формате: [Источник: имя_файла].
4. Если в КОНТЕКСТЕ действительно нет информации по сути вопроса, честно ответь: "В предоставленных фрагментах документации нет ответа на этот вопрос". Не выдумывай факты.

КОНТЕКСТ:
{context}"""),
            ("human", "Вопрос: {question}\nПодробный ответ:")
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
            print("Запуск Parent-Child поиска...")
            # k=2 или 3 идеально подходит, так как каждый чанк теперь большой и информативный
            docs = self.vs_manager.search(question, k=2)
            
            # Форматируем документы для промпта
            context = "\n\n---\n\n".join([
                f"[Источник: {doc.metadata.get('filename', 'Неизвестный файл')}]\n{doc.page_content}" 
                for doc in docs
            ])
            
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