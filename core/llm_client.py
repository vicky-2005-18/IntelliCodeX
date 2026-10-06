import json
import os
import requests
from typing import Generator


class OllamaLLM:
    def __init__(self, model: str = "qwen2.5-coder", host: str = "http://localhost:11434", num_ctx: int = 8192):
        self.model = model
        self.host = host.rstrip("/")
        self.num_ctx = num_ctx

    def set_model(self, model: str):
        """Dynamically switches active Ollama LLM model."""
        self.model = model

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation: characters / 3.5."""
        return int(len(text) / 3.5)

    def generate(self, prompt: str, system: str = "", temperature: float = 0.2, num_ctx: int = None) -> str:
        """Generate response with configurable context window and temperature."""
        ctx = num_ctx or self.num_ctx
        total_text = system + prompt
        estimated_tokens = self._estimate_tokens(total_text)
        
        if estimated_tokens > ctx:
            print(f"[!] Warning: Estimated prompt tokens ({estimated_tokens}) exceed context window ({ctx})")
        
        options = {"temperature": temperature, "num_ctx": ctx}
        
        try:
            resp = requests.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "system": system,
                    "stream": False,
                    "options": options,
                },
                timeout=300,
            )
            resp.raise_for_status()
            return resp.json().get("response", "")
        except requests.exceptions.Timeout:
            return "Local Ollama AI generation timed out (exceeded 300s). Try asking a more targeted question."
        except Exception as e:
            return f"Error communicating with local Ollama AI model: {e}"

    def stream_generate(self, prompt: str, system: str = "", temperature: float = 0.2, num_ctx: int = None) -> Generator[str, None, None]:
        """Yields response text tokens in real-time streaming chunks."""
        ctx = num_ctx or self.num_ctx
        total_text = system + prompt
        estimated_tokens = self._estimate_tokens(total_text)
        
        if estimated_tokens > ctx:
            print(f"[!] Warning: Estimated prompt tokens ({estimated_tokens}) exceed context window ({ctx})")
        
        options = {"temperature": temperature, "num_ctx": ctx}
        
        try:
            resp = requests.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "system": system,
                    "stream": True,
                    "options": options,
                },
                stream=True,
                timeout=300,
            )
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line:
                    chunk = json.loads(line.decode("utf-8"))
                    token = chunk.get("response", "")
                    if token:
                        yield token
        except Exception as e:
            yield f"\n[Error streaming from Ollama AI model: {e}]"

