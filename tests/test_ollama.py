"""Exercise the real OpenAI-compatible client against a local mocked transport."""
import json
from typing import Any

import httpx
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from config import Settings, settings
from llm_client import create_llm


def test_ollama_defaults() -> None:
    config = Settings(_env_file=None)
    assert config.llm_base_url == "http://127.0.0.1:11434/v1"
    assert config.llm_model_name == "qwen2.5:14b"
    assert config.knowledge_collection == "knowledge_base"
    assert config.user_docs_collection == "attachments"


def test_ollama_transport_and_tool_calling() -> None:
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://127.0.0.1:11434/v1/chat/completions"
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["model"] == settings.llm_model_name
        assert payload["max_tokens"] == settings.llm_max_tokens
        assert "max_completion_tokens" not in payload
        message: dict[str, Any] = {"role": "assistant", "content": "CHAT"}
        if "tools" in payload:
            message = {"role": "assistant", "content": "", "tool_calls": [{
                "id": "lookup-1", "type": "function", "function": {
                    "name": "lookup", "arguments": '{"query":"manual"}'}}]}
        return httpx.Response(200, json={"id": "local-test", "object": "chat.completion",
            "created": 0, "model": payload["model"], "choices": [{"index": 0,
            "message": message, "finish_reason": "tool_calls" if "tools" in payload else "stop"}]})

    @tool
    def lookup(query: str) -> str:
        """Search a document."""
        return query

    llm = create_llm()
    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False,
                      follow_redirects=False) as client:
        llm.root_client = llm.root_client.with_options(http_client=client)
        llm.client = llm.root_client.chat.completions
        assert llm.invoke([HumanMessage(content="Route this")]).content == "CHAT"
        response = llm.bind_tools([lookup]).invoke("Find the manual")
        assert response.tool_calls[0]["name"] == "lookup"
        assert response.tool_calls[0]["args"] == {"query": "manual"}
    assert len(requests) == 2
