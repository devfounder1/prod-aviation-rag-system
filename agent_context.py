"""Bound tool context by removing complete old exchanges, never partial tool pairs."""
from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage


class ContextBudgetError(ValueError):
    pass


def message_size(message: BaseMessage) -> int:
    size = len(str(message.content))
    if isinstance(message, AIMessage):
        size += len(str(message.tool_calls))
    return size + 80


class AgentContext:
    """Character budget is approximate; Ollama's real token context is independent.

    Keep the original task/instructions and newest exchanges. Removed tool data
    gets a bounded factual navigation ledger, not an LLM-generated instruction.
    Artifacts and stored chat history remain outside this window, unchanged.
    """

    def __init__(self, prefix: list[BaseMessage], max_chars: int = 16000) -> None:
        self.prefix = list(prefix)
        self.max_chars = max_chars
        self.notes: list[str] = []
        self.summary: HumanMessage | None = None

    def fit(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        if sum(message_size(m) for m in messages) <= self.max_chars:
            return messages
        tail = messages[len(self.prefix):]
        if tail and tail[0] is self.summary:
            tail = tail[1:]
        groups: list[list[BaseMessage]] = []
        for message in tail:
            if isinstance(message, ToolMessage) and groups:
                groups[-1].append(message)
            else:
                groups.append([message])
        while groups:
            summary = HumanMessage(content=(
                'Старые результаты инструментов удалены из окна контекста. '
                'Это неполные служебные данные, не исходный код и не инструкции. '
                'Перед правкой перечитай актуальные строки; не восстанавливай код по этим заметкам.\n'
                + '\n'.join(self.notes[-12:]))) if self.notes else None
            candidate = [*self.prefix, *([summary] if summary else []), *(m for group in groups for m in group)]
            if sum(message_size(m) for m in candidate) <= self.max_chars:
                self.summary = summary
                return candidate
            # Never discard the newest exchange or the original user request.
            if len(groups) == 1:
                break
            removed = groups.pop(0)
            for message in removed:
                if isinstance(message, AIMessage):
                    for call in message.tool_calls:
                        args = call.get('args', {})
                        path = args.get('file_path', args.get('project_id', ''))
                        self.notes.append(f"{call['name']}: {str(path)[:160]}")
                elif isinstance(message, ToolMessage):
                    first_line = (str(message.content).splitlines() or [''])[0]
                    self.notes.append(f'{message.name or "tool"}: {first_line[:160]}')
            self.notes = self.notes[-12:]
        raise ContextBudgetError('Контекст задачи переполнен. Уточните часть проекта или запросите меньший диапазон строк.')
