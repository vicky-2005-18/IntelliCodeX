import asyncio
import json
import os
import threading
from typing import Generator, Optional
import requests


# Global class-level inference lock to serialize access across OllamaLLM instances
# (Local Ollama instances on standard machines cannot safely process concurrent VRAM-heavy requests)
_GLOBAL_OLLAMA_THREAD_LOCK = threading.Lock()
_GLOBAL_OLLAMA_ASYNC_SEMAPHORE: Optional[asyncio.Semaphore] = None


def get_ollama_semaphore() -> asyncio.Semaphore:
    """Lazily initialize and return the global async semaphore in the running event loop."""
    global _GLOBAL_OLLAMA_ASYNC_SEMAPHORE
    if _GLOBAL_OLLAMA_ASYNC_SEMAPHORE is None:
        _GLOBAL_OLLAMA_ASYNC_SEMAPHORE = asyncio.Semaphore(1)
    return _GLOBAL_OLLAMA_ASYNC_SEMAPHORE


def detect_and_abort_repetition_loops(text: str, max_consecutive: int = 2) -> str:
    """Detects and aborts infinite repeated-line loops and short cyclic repetitions in generated text."""
    if not text:
        return text

    lines = text.split("\n")
    if len(lines) < 4:
        return text

    cleaned_lines = []
    consecutive_count = 1
    prev_line = None
    aborted = False

    for line in lines:
        stripped = line.strip()
        if stripped and stripped == prev_line:
            consecutive_count += 1
            if consecutive_count > max_consecutive:
                aborted = True
                break
        else:
            consecutive_count = 1
            if stripped:
                prev_line = stripped
        cleaned_lines.append(line)

    if aborted:
        return "\n".join(cleaned_lines)

    # Detect period-2 and period-3 repetition loops
    n = len(lines)
    for k in (2, 3):
        if n >= k * 3:
            b1 = [l.strip() for l in lines[-k:]]
            b2 = [l.strip() for l in lines[-2 * k:-k]]
            b3 = [l.strip() for l in lines[-3 * k:-2 * k]]
            if b1 == b2 == b3 and any(bool(x) for x in b1):
                return "\n".join(lines[:-k])

    return text


class OllamaLLM:
    def __init__(
        self,
        model: str = "qwen2.5-coder:7b",
        host: str = "http://localhost:11434",
        num_ctx: int = 8192,
        temperature: float = 0.0,
        num_predict: int = 800,
        repeat_penalty: float = 1.1,
    ):
        self.model = model or os.getenv("OLLAMA_LLM_MODEL", "qwen2.5-coder:7b")
        self.host = host.rstrip("/")
        self.num_ctx = int(os.getenv("OLLAMA_NUM_CTX", str(num_ctx)))
        self.temperature = float(os.getenv("OLLAMA_TEMPERATURE", str(temperature)))
        self.num_predict = int(os.getenv("OLLAMA_NUM_PREDICT", str(num_predict)))
        self.repeat_penalty = float(os.getenv("OLLAMA_REPEAT_PENALTY", str(repeat_penalty)))
        self._lock = _GLOBAL_OLLAMA_THREAD_LOCK

    def set_model(self, model: str):
        """Dynamically switches active Ollama LLM model."""
        self.model = model

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation: characters / 3.5."""
        return int(len(text) / 3.5)

    def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: Optional[float] = None,
        num_ctx: Optional[int] = None,
        num_predict: Optional[int] = None,
        repeat_penalty: Optional[float] = None,
    ) -> str:
        """Generate response with configurable context window, temperature, num_predict, and repetition penalty."""
        ctx = num_ctx or self.num_ctx
        temp = self.temperature if temperature is None else temperature
        predict = self.num_predict if num_predict is None else num_predict
        penalty = self.repeat_penalty if repeat_penalty is None else repeat_penalty

        total_text = system + prompt
        estimated_tokens = self._estimate_tokens(total_text)
        
        if estimated_tokens > ctx:
            print(f"[!] Warning: Estimated prompt tokens ({estimated_tokens}) exceed context window ({ctx})")
        
        options = {
            "temperature": temp,
            "num_ctx": ctx,
            "num_predict": predict,
            "repeat_penalty": penalty,
        }
        
        with self._lock:
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
                raw_ans = resp.json().get("response", "")
                return detect_and_abort_repetition_loops(raw_ans)
            except requests.exceptions.Timeout:
                return "Local Ollama AI generation timed out (exceeded 300s). Try asking a more targeted question."
            except Exception as e:
                return f"Error communicating with local Ollama AI model: {e}"

    def stream_generate(
        self,
        prompt: str,
        system: str = "",
        temperature: Optional[float] = None,
        num_ctx: Optional[int] = None,
        num_predict: Optional[int] = None,
        repeat_penalty: Optional[float] = None,
    ) -> Generator[str, None, None]:
        """Yields response text tokens in real-time streaming chunks with lock held during active streaming."""
        ctx = num_ctx or self.num_ctx
        temp = self.temperature if temperature is None else temperature
        predict = self.num_predict if num_predict is None else num_predict
        penalty = self.repeat_penalty if repeat_penalty is None else repeat_penalty

        total_text = system + prompt
        estimated_tokens = self._estimate_tokens(total_text)
        
        if estimated_tokens > ctx:
            print(f"[!] Warning: Estimated prompt tokens ({estimated_tokens}) exceed context window ({ctx})")
        
        options = {
            "temperature": temp,
            "num_ctx": ctx,
            "num_predict": predict,
            "repeat_penalty": penalty,
        }
        
        with self._lock:
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



