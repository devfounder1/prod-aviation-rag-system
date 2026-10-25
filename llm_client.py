"""Универсальный клиент для любого OpenAI-совместимого сервера (Ollama / llama-server)."""
import json
import time
from pathlib import Path
import requests

BASE_DIR = Path(__file__).resolve().parent

def load_config(path=None):
    p = Path(path) if path else BASE_DIR / "config.json"
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

class LLMClient:
    def __init__(self, base_url=None, model=None, config=None):
        cfg = (config or load_config()).get("llm", {})
        self.base_url = (base_url or cfg.get("base_url", "http://127.0.0.1:11434/v1")).rstrip("/")
        self.model = model or cfg.get("model", "qwen2.5:14b")
        self.temperature = cfg.get("temperature", 0.1)
        self.max_tokens = cfg.get("max_tokens", 2048)

    def health(self, timeout=2):
        try:
            return requests.get(f"{self.base_url}/models", timeout=timeout).status_code == 200
        except Exception:
            return False

    def wait_ready(self, tries=60, delay=1.0):
        for _ in range(tries):
            if self.health():
                return True
            time.sleep(delay)
        return False

    def chat(self, messages, temperature=None, max_tokens=None, timeout=600):
        r = requests.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature if temperature is None else temperature,
                "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def simple(self, system: str, user: str, **kw):
        return self.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}], **kw)