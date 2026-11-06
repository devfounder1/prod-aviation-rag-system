"""
AI Агент на базе LangGraph (LangChain 1.x+)
Управляет циклом мышления, выбора инструментов и самокоррекции кода.
"""
from typing import Annotated, Literal, TypedDict
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from agent_tools import ALL_TOOLS


class AgentState(TypedDict):
    """Состояние агента"""
    messages: Annotated[list[BaseMessage], lambda x, y: x + y]
    iteration: int


class CodeAgent:
    def __init__(self, llm: BaseChatModel, max_iterations: int = 50):  # Увеличили до 8
        
        self.llm = llm.bind_tools(ALL_TOOLS)
        self.tools = ALL_TOOLS
        self.max_iterations = max_iterations
        self.max_test_attempts = 10 
        
        # Создаём узел для выполнения инструментов
        self.tool_node = ToolNode(ALL_TOOLS)
        
        # Системный промпт
        tools_description = "\n".join([f"- {t.name}: {t.description}" for t in ALL_TOOLS])
        system_prompt = f"""Ты — BUTUZIK, автономный ИИ-инженер. Твоя задача — выполнять задачи по написанию, исправлению и тестированию кода.

## АЛГОРИТМ РАБОТЫ:

### Для задач по коду (исправить/написать/добавить):
1. Прочитай файл через `read_file('attached/ИМЯ_ФАЙЛА')`
2. Напиши исправленный/новый код
3. Протестируй через `run_code_test(code="КОД", test_code="ТЕСТЫ")`
4. Если тест не прошёл — исправь и тестируй снова (максимум 10 попыток)
5. Когда тест прошёл — сохрани через `update_attached_file(file_name="ИМЯ", new_content="КОД")`

### Для задач по документам (DOCX, TXT, MD):
1. Прочитай через `read_file('attached/ИМЯ_ФАЙЛА')`
2. Отредактируй текст
3. Сохрани через `write_file('новое_имя.docx', 'текст')`

### Для точечных изменений в больших файлах (>200 строк):
1. Используй `get_file_structure(file_path)` чтобы увидеть структуру
2. Используй `find_in_file(file_path, pattern)` чтобы найти нужное место
3. Используй `read_file_lines(file_path, start, end)` чтобы прочитать участок
4. Используй `replace_lines(file_path, start, end, new_content)` чтобы заменить
5. НЕ переписывай файл целиком!

## ПРАВИЛА:
1. НЕ задавай уточняющих вопросов, если задача понятна — просто выполняй
2. НЕ анализируй смысл файла, если задача механическая (добавить строку, заменить текст)
3. При записи кода используй РЕАЛЬНЫЕ переносы строк, а не символы `\n`
4. Тестируй код перед сохранением (максимум 10 попыток)
5. Для документов не нужно тестирование

## ИНСТРУМЕНТЫ:
{tools_description}

## СТРАТЕГИЯ РАБОТЫ С БОЛЬШИМИ ФАЙЛАМИ (>200 строк):

Если файл больше 200 строк, ЗАПРЕЩЕНО переписывать его целиком через `update_attached_file` или `write_file`.
Вместо этого действуй по алгоритму:

### Шаг 1: Разведка
- Вызови `get_file_structure(file_path)` чтобы увидеть структуру файла (функции, классы, номера строк)
- Это даст тебе "карту" файла без чтения всего содержимого

### Шаг 2: Локализация
- Если нужно изменить конкретную функцию — используй `find_in_file(file_path, "def имя_функции")` чтобы найти её точный номер строки
- Или используй `read_file_lines(file_path, start, end)` чтобы прочитать только нужный участок

### Шаг 3: Точечная замена
- Используй `replace_lines(file_path, start_line, end_line, new_content)` для изменения ТОЛЬКО нужных строк
- НЕ трогай остальной код!
- Бэкап создаётся автоматически

### Шаг 4: Тестирование
- После каждого точечного изменения запускай `run_code_test` для проверки
- Если тест упал — откатывай изменения через бэкап (читай .bak файл и восстанавливай)

### ПРАВИЛА:
- Меняй максимум 1-2 функции за итерацию
- НИКОГДА не переписывай файл целиком, если он больше 200 строк
- Всегда сначала ЧИТАЙ структуру, потом ЧИТАЙ нужный участок, потом МЕНЯЙ

## ПРИМЕР ПРАВИЛЬНОЙ РАБОТЫ С БОЛЬШИМ ФАЙЛОМ:

Пользователь: "Добавь обработку ошибок в функцию calculate в файле big_module.py"

Правильный алгоритм:
1. `get_file_structure('attached/big_module.py')` → видим что `calculate` на строках 340-380
2. `read_file_lines('attached/big_module.py', 340, 380)` → читаем только эту функцию
3. `replace_lines('attached/big_module.py', 340, 380, 'новый код с обработкой ошибок')`
4. `run_code_test(...)` → проверяем что работает
5. Отдаём результат пользователю

НЕПРАВИЛЬНЫЙ алгоритм (ЗАПРЕЩЕНО):
1. `read_file('attached/big_module.py')` → читаем ВЕСЬ файл (1000+ строк)
2. Переписываем весь файл целиком → теряем код, ломаем структуру

## ФОРМАТ ФИНАЛЬНОГО ОТВЕТА:
Когда задача выполнена:
1. Краткое описание что было сделано
2. Финальный код (в блоке ```)
3. Результат тестирования (прошёл/не прошёл, выводы)
"""

        self.prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="messages"),
        ])
        
        # Строим граф агента
        self.graph = self._build_graph()
    
    def _should_continue(self, state: AgentState) -> Literal["tools", "end"]:
        """Решает, продолжать ли цикл или завершить"""
        messages = state["messages"]
        iteration = state["iteration"]
        
        # Если превысили лимит итераций — завершаем
        if iteration >= self.max_iterations:
            print(f"[AGENT] Достигнут лимит итераций ({self.max_iterations})", flush=True)
            return "end"
        
        # Если последнее сообщение содержит вызов инструмента, продолжаем
        last_message = messages[-1]
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            return "tools"
        
        return "end"
    
    def _call_model(self, state: AgentState) -> dict:
        """Вызов LLM с контролем попыток тестирования"""
        messages = state["messages"]
        iteration = state["iteration"]
        
        # Считаем сколько раз агент уже запускал тесты
        test_attempts = 0
        for msg in messages:
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.get('name') == 'run_code_test':
                        test_attempts += 1
        
        # Если превысили лимит попыток тестирования — принудительно останавливаем
        if test_attempts >= self.max_test_attempts:
            from langchain_core.messages import AIMessage
            stop_msg = AIMessage(content=(
                f"Достигнут лимит попыток тестирования ({self.max_test_attempts}). "
                f"Отдай пользователю лучший текущий вариант кода "
                f"с описанием оставшихся проблем. НЕ запускай больше тестов."
            ))
            return {
                "messages": [stop_msg],
                "iteration": iteration + 1
            }
        
        # Формируем сообщения с системным промптом
        full_messages = self.prompt.format_messages(messages=messages)
        response = self.llm.invoke(full_messages)
        
        # Транслируем в UI, какой инструмент вызывается и с какими аргументами
        if self._on_step and hasattr(response, 'tool_calls') and response.tool_calls:
            for tc in response.tool_calls:
                args_preview = str(tc.get('args', ''))[:400]
                tool_name = tc['name']
                # Показываем прогресс тестирования
                if tool_name == 'run_code_test':
                    self._on_step(f"🧪 Тест {test_attempts + 1}/{self.max_test_attempts}...")
                else:
                    self._on_step(f"Вызываю инструмент: `{tool_name}`\n```\n{args_preview}\n```")
        
        # Логируем мысль агента
        if hasattr(response, 'content') and response.content:
            print(f"[AGENT] Итерация {iteration + 1} (тестов: {test_attempts}): {response.content[:100]}...", flush=True)
        else:
            print(f"[AGENT] Итерация {iteration + 1}: Вызов инструмента...", flush=True)
        
        return {
            "messages": [response],
            "iteration": iteration + 1
        }
    
    def _run_tools(self, state: AgentState) -> dict:
        """Выполняет инструменты и транслирует результаты в UI"""
        result = self.tool_node.invoke(state)   # Правильный вызов в LangGraph 1.x
        if self._on_step:
            for msg in result.get("messages", []):
                content = msg.content if hasattr(msg, 'content') else str(msg)
                self._on_step(f"Результат инструмента:\n```\n{content[:400]}\n```")
        return result   
    
    def _build_graph(self):
        """Строит граф агента"""
        workflow = StateGraph(AgentState)
        
        # Добавляем узлы
        workflow.add_node("agent", self._call_model)
        workflow.add_node("tools", self._run_tools)
        
        # Определяем точки входа
        workflow.add_edge(START, "agent")
        
        # Условный переход после агента
        workflow.add_conditional_edges(
            "agent",
            self._should_continue,
            {
                "tools": "tools",
                "end": END
            }
        )
        
        # После инструментов возвращаемся к агенту
        workflow.add_edge("tools", "agent")
        
        return workflow.compile()
    
    def run(self, task: str, chat_history: list = None, on_step=None) -> str:
        """Запускает агента на выполнение задачи с учетом истории диалога"""
        self._on_step = on_step
        try:
            messages = []
            
            # 🆕 Добавляем историю чата, если она передана
            if chat_history and len(chat_history) > 0:
                history_text = "ИСТОРИЯ ДИАЛОГА:\n"
                # Берем последние 5 сообщений для контекста
                for msg in chat_history[-5:]:
                    role = "Пользователь" if msg.get("role") == "user" else "Ассистент"
                    # Обрезаем слишком длинные сообщения, чтобы не переполнять контекст
                    content = msg.get("content", "")[:500] 
                    history_text += f"{role}: {content}\n"
                
                from langchain_core.messages import SystemMessage
                messages.append(SystemMessage(content=history_text))
            
            # Добавляем текущую задачу
            from langchain_core.messages import HumanMessage
            messages.append(HumanMessage(content=task))
            
            print(f"\n[AGENT] Запуск агента с задачей: '{task}'", flush=True)
            
            initial_state = {
                "messages": messages,
                "iteration": 0
            }
            
            # Запускаем граф
            final_state = self.graph.invoke(initial_state)
            
            # Извлекаем финальный ответ
            final_message = final_state["messages"][-1]
            output = final_message.content if hasattr(final_message, 'content') else str(final_message)
            iterations = final_state["iteration"]
            
            if iterations > 1:
                output += f"\n*(Агент выполнил {iterations} итераций)*"
                
            return output
            
        except Exception as e:
            print(f"[AGENT] Критическая ошибка: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return f"Агент столкнулся с критической ошибкой: {str(e)}"