"""Single Ollama endpoint for routing, chat, vision and agent tools."""
from __future__ import annotations
from typing import Any
import httpx
from pydantic import SecretStr
from langchain_openai import ChatOpenAI
from langchain_core.language_models import LanguageModelInput
from config import Settings, settings


class OllamaChatOpenAI(ChatOpenAI):
    """Adapt the OpenAI client's newer token parameter to Ollama's API."""
    def _get_request_payload(self, input_: LanguageModelInput, *,
                             stop: list[str] | None = None,
                             **kwargs: Any) -> dict[str, Any]:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        if "max_completion_tokens" in payload:
            payload["max_tokens"] = payload.pop("max_completion_tokens")
        return payload


def create_llm(model: str | None = None) -> ChatOpenAI:
    Settings.local_endpoint(settings.llm_base_url)
    # Disable environment proxies and redirects: no request may escape loopback.
    return OllamaChatOpenAI(
        model=model or settings.llm_model_name,
        base_url=settings.llm_base_url, api_key=SecretStr(settings.llm_api_key),
        temperature=settings.llm_temperature, max_completion_tokens=settings.llm_max_tokens,
        timeout=120, max_retries=1, use_responses_api=False,
        http_client=httpx.Client(trust_env=False, follow_redirects=False),
        http_async_client=httpx.AsyncClient(trust_env=False, follow_redirects=False),
    )


class LLMClient:
    """Compatibility wrapper around the same configured local model."""
    def __init__(self, model: str | None = None) -> None:
        self.llm = create_llm(model)

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> str:
        return str(self.llm.invoke(messages, **kwargs).content)

    def simple(self, system: str, user: str, **kwargs: Any) -> str:
        return self.chat([{"role": "system", "content": system},
                          {"role": "user", "content": user}], **kwargs)
