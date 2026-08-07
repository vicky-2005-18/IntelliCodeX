"""
Local AI Server client — talks to Ollama running qwen2.5-coder (or any model
you've pulled). This is the "centralized local AI server" from the paper.
"""
import requests


class OllamaLLM:
    def __init__(self, model: str = "qwen2.5-coder", host: str = "http://localhost:11434"):
        self.model = model
        self.host = host.rstrip("/")

    def generate(self, prompt: str, system: str = "", temperature: float = 0.2) -> str:
        resp = requests.post(
            f"{self.host}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "system": system,
                "stream": False,
                "options": {"temperature": temperature},
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["response"]
