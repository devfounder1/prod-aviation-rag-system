from pathlib import Path
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from pydantic import ValidationError

from config import Settings
from smart_rag import SmartRAG
from ai_agent import LocalAgent


@pytest.mark.parametrize("url", ["https://api.openai.com/v1", "http://localhost:1234/v1",
    "http://127.0.0.1:1234/v1", "http://127.0.0.1:11434/v1?x=1"])
def test_reject_non_ollama_endpoint(url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(llm_base_url=url, _env_file=None)


@pytest.mark.parametrize("intent", ["CHAT", "SEARCH", "AGENT"])
def test_routes(intent: str) -> None:
    rag = SmartRAG()
    rag.llm = MagicMock()
    rag.llm.invoke.return_value = AIMessage(content=intent)
    assert rag.route("question") == intent


def test_chat_never_loads_retrieval() -> None:
    rag = SmartRAG()
    rag.route = MagicMock(return_value="CHAT")
    rag.search_documents = MagicMock(side_effect=AssertionError("Must not search"))
    rag.llm = MagicMock()
    rag.llm.stream.return_value = [AIMessageChunk(content="Hello")]
    assert rag.query_stream("Hi") == ("Hello", [])


def test_search_and_agent_use_same_scoped_search() -> None:
    rag = SmartRAG()
    rag.route = MagicMock(return_value="SEARCH")
    rag.search_documents = MagicMock(return_value=("[Источник: a.pdf] Fact", ["a.pdf"]))
    rag.llm = MagicMock()
    rag.llm.stream.return_value = [AIMessageChunk(content="Fact")]
    assert rag.query_stream("question", chat_id="chat-a")[1] == ["a.pdf"]
    tools = rag._agent_tools("chat-a", [])
    search = next(t for t in tools if t.name == "search_documents")
    assert "Fact" in search.invoke({"query": "question"})
    assert rag.search_documents.call_args.args == ("question", "chat-a")
    assert "execute_python_code" not in {t.name for t in tools}


def test_universal_agent_tool_loop() -> None:
    from langchain_core.tools import tool

    @tool
    def lookup(query: str) -> str:
        """Look up a document."""
        return "Fact from manual"

    model = MagicMock()
    model.bind_tools.return_value.invoke.side_effect = [
        AIMessage(content="", tool_calls=[{"name": "lookup", "args": {"query": "fact"}, "id": "1"}]),
        AIMessage(content="Summary of manual"),
    ]
    assert LocalAgent(model).run("Summarize", tools=[lookup]) == "Summary of manual"
    messages = model.bind_tools.return_value.invoke.call_args.args[0]
    assert any(getattr(m, "tool_call_id", None) == "1" for m in messages)


def test_agent_routes_automatically_and_cancel_prevents_work() -> None:
    rag = SmartRAG()
    rag.route = MagicMock(return_value="AGENT")
    rag.code_agent = MagicMock()
    rag.code_agent.run.return_value = "Created summary"
    assert rag.query_stream("Create summary", chat_id="c")[0] == "Created summary"
    rag.code_agent.run.reset_mock()
    rag.query_stream("Create", cancel_flag={"cancelled": True})
    rag.code_agent.run.assert_not_called()


def test_workspace_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import agent_tools
    workspace = tmp_path / "work"
    workspace.mkdir()
    monkeypatch.setattr(agent_tools, "AGENT_WORKSPACE", workspace)
    (workspace / "escape").symlink_to(tmp_path, target_is_directory=True)
    for path in ("../escape.txt", str(tmp_path / "escape.txt"), "escape/out.txt"):
        assert "Ошибка" in agent_tools.write_file.invoke({"file_path": path, "content": "bad"})
    assert not (tmp_path / "escape.txt").exists()


def test_attachment_search_requires_chat() -> None:
    from document_processor import retrieve_user_context
    with pytest.raises(ValueError, match="chat_id"):
        retrieve_user_context("question")


def test_async_entry_offloads_work() -> None:
    import asyncio
    import threading
    rag = SmartRAG()
    caller = threading.get_ident()
    def worker(question: str, **kwargs: object) -> tuple[str, list[str]]:
        assert threading.get_ident() != caller
        return question, []
    rag.query_stream = worker
    assert asyncio.run(rag.aquery("Hi")) == ("Hi", [])


def test_rrf_merges_same_parent_across_retrievers() -> None:
    from hybrid_retriever import HybridRetriever
    from langchain_core.documents import Document
    retriever = HybridRetriever.__new__(HybridRetriever)
    a = Document(page_content="parent", metadata={"parent_id": "a"})
    b = Document(page_content="other", metadata={"parent_id": "b"})
    a_copy = Document(page_content="parent", metadata={"parent_id": "a"})
    result = retriever._reciprocal_rank_fusion([b, a], [a_copy], k=2)
    assert [doc.metadata["parent_id"] for doc in result] == ["a", "b"]
