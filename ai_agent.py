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
    def __init__(self, llm: BaseChatModel, max_iterations: int = 8):  # Увеличили до 8
        # ИСПРАВЛЕНО: используем bind_tools для привязки инструментов
        self.llm = llm.bind_tools(ALL_TOOLS)
        self.tools = ALL_TOOLS
        self.max_iterations = max_iterations
        
        # Создаём узел для выполнения инструментов
        self.tool_node = ToolNode(ALL_TOOLS)
        
        # Системный промпт
        tools_description = "\n".join([f"- {t.name}: {t.description}" for t in ALL_TOOLS])
        system_prompt = f"""Ты — BUTUZIK, автономный ИИ-инженер. Твоя задача — выполнять сложные задачи, требующие написания и запуска кода.

ПРАВИЛА РАБОТЫ:
1. Анализируй задачу пользователя.
2. Используй доступные инструменты: `read_file`, `write_file`, `list_directory`, `execute_python_code`, `search_knowledge_base`, `update_attached_file`.

3. **СТРОГИЙ АЛГОРИТМ РЕДАКТИРОВАНИЯ КОДА (ДЕЛАЙ ПО ШАГАМ, КАЖДЫЙ ШАГ — ОТДЕЛЬНЫЙ ВЫЗОВ):**
   - **ШАГ 1 (Чтение):** Прочитай файл через `read_file('attached/ИМЯ_ФАЙЛА')`. Запомни ВСЁ содержимое.
   - **ШАГ 2 (Генерация):** В уме сформируй ПОЛНЫЙ новый код. Скопируй ВСЕ строки оригинала, добавь новые в нужные места. НИКОГДА не удаляй существующие print, комментарии или логику, если об этом прямо не просят.
   - **ШАГ 3 (Внутренний тест):** Вызови `execute_python_code` с параметрами: `code="ПОЛНЫЙ_НОВЫЙ_КОД", require_approval=False`. Это запустит код в песочнице БЕЗ показа пользователю.
   - **ШАГ 4 (Анализ и исправление):** 
     * Если тест вернул ошибку (STDERR): проанализируй traceback, исправь код и повтори ШАГ 3.
     * Если тест прошёл успешно (STDOUT без ошибок): переходи к ШАГУ 5.
   - **ШАГ 5 (Финальное сохранение):** ТОЛЬКО после успешного теста вызови `update_attached_file(file_name="ИМЯ", new_content="ПОЛНЫЙ_ПРОВЕРЕННЫЙ_КОД")`. Это покажет код пользователю для финального одобрения и создаст .bak бэкап.

4. НИКОГДА не вызывай `update_attached_file` без предварительного успешного тестирования через `execute_python_code(require_approval=False)`.
5. Не пытайся сделать всё за одну итерацию. Используй 4-6 итераций на полный цикл.
6. НИКОГДА не используй запрещённые модули (os.system, subprocess и т.д.).

Доступные инструменты:
{tools_description}
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
        """Вызов LLM"""
        messages = state["messages"]
        
        # Формируем сообщения с системным промптом
        full_messages = self.prompt.format_messages(messages=messages)
        
        response = self.llm.invoke(full_messages)

        # Транслируем в UI, какой инструмент вызывается и с какими аргументами
        if self._on_step and hasattr(response, 'tool_calls') and response.tool_calls:
            for tc in response.tool_calls:
                args_preview = str(tc.get('args', ''))[:400]
                self._on_step(f"Вызываю инструмент: `{tc['name']}`\n```\n{args_preview}\n```")

        # Логируем мысль агента
        if hasattr(response, 'content') and response.content:
            print(f"[AGENT] Итерация {state['iteration'] + 1}: {response.content[:100]}...", flush=True)
        else:
            print(f"[AGENT] Итерация {state['iteration'] + 1}: Вызов инструмента...", flush=True)
        
        return {
            "messages": [response],
            "iteration": state["iteration"] + 1
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
    
    def run(self, task: str, on_step=None) -> str:
        """Запускает агента на выполнение задачи"""
        self._on_step = on_step  # callback для живой трансляции шагов в UI
        try:
            print(f"\n[AGENT] Запуск агента с задачей: '{task}'", flush=True)
            
            initial_state = {
                "messages": [HumanMessage(content=task)],
                "iteration": 0
            }
            
            # Запускаем граф
            final_state = self.graph.invoke(initial_state)
            
            # Извлекаем финальный ответ
            final_message = final_state["messages"][-1]
            output = final_message.content if hasattr(final_message, 'content') else str(final_message)
            
            iterations = final_state["iteration"]
            if iterations > 1:
                output += f"\n\n*(Агент выполнил {iterations} итераций)*"
            
            return output
            
        except Exception as e:
            print(f"[AGENT] Критическая ошибка: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return f"Агент столкнулся с критической ошибкой: {str(e)}"