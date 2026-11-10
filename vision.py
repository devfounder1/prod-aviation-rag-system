"""Shared multimodal input and actionable local-backend capability errors."""
from __future__ import annotations
import base64
from pathlib import Path
import re
from typing import Any

from exceptions import LLMError

IMAGE_SUFFIXES = {'.png': 'image/png', '.jpg': 'image/jpeg',
                  '.jpeg': 'image/jpeg', '.webp': 'image/webp'}


class UnsupportedImageModelError(LLMError):
    """The selected model rejected multimodal input; user can retry with vision."""


def prefer_image_chat(question: str, attachments: list[dict[str, str]] | None) -> bool:
    """A plain image question needs vision, not unrelated document retrieval.

    Explicit document references and file actions still go through the router.
    The caller's explicit agent switch always takes precedence.
    """
    if not attachments or not all(Path(a.get('path', '')).suffix.lower() in IMAGE_SUFFIXES
                                  for a in attachments):
        return False
    needs_documents_or_tools = re.search(
        r'документ|руководств|инструкц|баз[аеуы].*знани|manual|documentation|knowledge.?base|'
        r'созда|сохран|запиш|измен|исправ|удал|create|save|write|edit|update|delete',
        question, re.IGNORECASE)
    return needs_documents_or_tools is None


def image_content(question: str, attachments: list[dict[str, str]] | None
                  ) -> tuple[list[str | dict[str, Any]], list[str]]:
    content: list[str | dict[str, Any]] = [{'type': 'text', 'text': question}]
    names: list[str] = []
    for attachment in attachments or []:
        path = Path(attachment.get('path', ''))
        mime = IMAGE_SUFFIXES.get(path.suffix.lower())
        if mime:
            encoded = base64.b64encode(path.read_bytes()).decode('ascii')
            content.append({'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{encoded}'}})
            names.append(path.name)
    return content, names


def unsupported_image_error(exc: Exception, model: str,
                            attachments: list[dict[str, str]] | None
                            ) -> UnsupportedImageModelError | None:
    if not any(Path(a.get('path', '')).suffix.lower() in IMAGE_SUFFIXES for a in attachments or []):
        return None
    # Match the actual Ollama error, independent of the SDK's exception class name.
    # Do not translate unrelated image corruption, connection or server errors.
    message = str(getattr(exc, 'body', None) or exc).lower()
    unsupported = any(phrase in message for phrase in (
        'does not support multimodal', 'does not support images',
        'does not support image input', 'does not support vision',
        'image input is not supported', 'images are not supported',
    ))
    if not unsupported:
        return None
    return UnsupportedImageModelError(
        f'Модель «{model}» не поддерживает изображения. '
        'Откройте «Настройки → LLM Модель» и выберите установленную vision-модель '
        '(например, «Qwen 2.5 VL (7B, изображения)» — qwen2.5vl:7b). '
        'Затем повторите вопрос с изображением. '
        'Модель автоматически не переключается; обработка остаётся локальной в Ollama.'
    )
