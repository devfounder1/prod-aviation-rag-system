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
    def __init__(self, llm: BaseChatModel, max_iterations: int = 3):
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
2. Используй доступные инструменты (`read_file`, `write_file`, `list_directory`, `execute_python_code`) для решения задачи.
3. **ЦИКЛ САМОКОРРЕКЦИИ:** Если `execute_python_code` возвращает ошибку (STDERR), НЕ сдавайся. Проанализируй ошибку, исправь код и запусти его снова. У тебя есть максимум {max_iterations} попытки на одну задачу.
4. Если задача решена, кратко опиши пользователю, что было сделано, и покажи финальный результат или путь к созданному файлу.
5. Если после {max_iterations} попыток код не работает, честно сообщи пользователю о последней ошибке и попроси уточнений.
6. НИКОГДА не используй запрещённые модули (os.system, subprocess и т.д.), инструменты сами их заблокируют.

Доступные инструменты:
{tools_description}

Имя инструмента должно использоваться точно так, как указано выше."""

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
        
        # Логируем мысль агента
        if hasattr(response, 'content') and response.content:
            print(f"[AGENT] Итерация {state['iteration'] + 1}: {response.content[:100]}...", flush=True)
        else:
            print(f"[AGENT] Итерация {state['iteration'] + 1}: Вызов инструмента...", flush=True)
        
        return {
            "messages": [response],
            "iteration": state["iteration"] + 1
        }
    
    def _build_graph(self):
        """Строит граф агента"""
        workflow = StateGraph(AgentState)
        
        # Добавляем узлы
        workflow.add_node("agent", self._call_model)
        workflow.add_node("tools", self.tool_node)
        
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
    
    def run(self, task: str) -> str:
        """Запускает агента на выполнение задачи"""
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