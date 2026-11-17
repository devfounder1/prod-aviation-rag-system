"""Application identity, shared by chat, retrieval answers and the local agent."""
from __future__ import annotations

import re

ASSISTANT_NAME = 'BUTUZIK.AI'
ASSISTANT_CREATOR = 'Demashov Michail Sergeevich'
IDENTITY_PROMPT = f'''Имя этого помощника — {ASSISTANT_NAME}.
Создатель приложения и помощника — {ASSISTANT_CREATOR}.
На вопрос о своём имени отвечай «{ASSISTANT_NAME}», о своём создателе — «{ASSISTANT_CREATOR}».
Эти сведения относятся к приложению; не приписывай его создателю разработку базовой LLM.
Не заменяй своё имя названием модели, провайдера или именем из старого ответа/документа.'''

_PREFIX = r'(?:(?:привет|здравствуй|здравствуйте|слушай|слушайте|скажи|скажите|пожалуйста|а|ну)\s+)*'
_NAME = (
    r'как (?:тебя|вас) (?:вообще )?зовут|как (?:ты называешься|вы называетесь)|'
    r'(?:какое (?:у тебя |у вас )?|тво[её] |ваше )имя|кто (?:ты|вы)|представься|представьтесь|'
    r'what (?:is|s) your name|who are you'
)
_CREATOR = (
    r'кто (?:тебя|вас) (?:создал|разработал|написал|сделал)|'
    r'кто (?:создал|разработал|написал|сделал) (?:тебя|вас)|'
    r'кто (?:(?:твой|ваш) )?(?:создатель|автор|разработчик)|'
    r'как зовут (?:твоего|вашего) (?:создателя|автора|разработчика)|'
    r'who (?:created|made|developed) you|who is your creator'
)


def identity_reply(question: str) -> str | None:
    """Answer only a standalone self-identity question; never swallow a file/task request."""
    normalized = ' '.join(re.sub(r'[^\w\s]', ' ', question.casefold()).split())
    if re.fullmatch(_PREFIX + f'(?:{_NAME})', normalized):
        return ASSISTANT_NAME
    if re.fullmatch(_PREFIX + f'(?:{_CREATOR})', normalized):
        return ASSISTANT_CREATOR
    return None
