"""Recognize an explicit request for a saved artifact, never execute prose/code."""
from __future__ import annotations

import re

FILE_OBJECT = re.compile(r'файл|скрипт|files?\b|scripts?\b|\.(?:py|txt|md|docx|json|csv|html)\b', re.I)
ACTIONS = re.compile(
    r'\b(?:создай(?:те)?|сделай(?:те)?|напиши(?:те)?|сохрани(?:те)?|запиши(?:те)?|'
    r'измени(?:те)?|исправь(?:те)?|отредактируй(?:те)?|обнови(?:те)?|добавь(?:те)?|'
    r'create|save|write|edit|update|append|fix)\b', re.I)


def file_delivery_requested(task: str) -> bool:
    """A completion guard inside AGENT, not permission or a routing fallback.

    Look only at this user's task. Examples/old messages/tool results cannot
    enable writes. Modal approval and the file tools remain the write boundary.
    """
    # The desktop app appends attachment-copy paths for the model. A filename
    # there is input metadata, not the user's instruction to save an output.
    text = task.split('\nДоступные копии вложений:',1)[0]
    text = re.sub(r'```.*?```', '', text, flags=re.S).strip()
    text = re.sub(r'«[^»\n]*»|"[^"\n]*"|“[^”\n]*”',
                  lambda m:'' if ACTIONS.search(m.group()) else m.group(),text)
    if not FILE_OBJECT.search(text):
        return False
    # A complaint about missing output is a renewed delivery request, unlike
    # an imperative telling the assistant not to create/save anything.
    if re.search(r'\b(?:ты|вы)\b.{0,35}\bне\s+(?:сохранил[аи]?|создал[аи]?|записал[аи]?)\b', text, re.I):
        return True
    for match in ACTIONS.finditer(text):
        prefix = text[max(0,match.start()-60):match.start()]
        if re.search(r'\b(?:не(?:\s+(?:надо|нужно))?|do\s+not|don.t)\s*$', prefix, re.I):
            continue
        if re.search(r'\b(?:как(?:\s+\w+){0,3}|how\s+(?:to|(?:can|do|should|could)\s+(?:i|you|we)))\s*$', prefix, re.I):
            continue
        return True
    return False


FILE_DELIVERY_INSTRUCTION = '''Текущий запрос требует фактического сохранения файлов.
Код в Markdown и обещание «сейчас сохраню» не создают файл. Вызови write_file
для каждого запрошенного нового файла или подходящий инструмент изменения.
Если файлов несколько, сохрани все, не останавливайся после первого.
Не проси подтверждение текстом: приложение само покажет кнопки с точным содержимым.
Завершить эту задачу можно только после результатов записи инструментами.
Отказ пользователя, отмена и ошибка записи не являются успешным сохранением.'''

FILE_DELIVERY_RETRY = '''В предыдущем ответе нет подтверждённого файла: показан текст
вместо выполнения запроса. Используй инструменты записи сейчас. Если нужен прошлый
код, он есть в истории этого запроса; не выводи его снова вместо сохранения.
Вызов инструмента должен быть настоящим tool call, а не JSON/кодовым блоком в тексте.
Сохрани каждый запрошенный файл. Содержимое и путь подтвердит пользователь кнопкой.'''
