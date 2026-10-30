import threading
import time
from collections import deque

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError
from openai.types.chat import ChatCompletionMessageParam

from .config import settings


class LLMError(Exception):
    pass


class RateLimiter:
    """Sliding-window limiter so we never exceed a provider's requests/minute."""

    def __init__(self, rpm: int):
        self.rpm, self.lock = rpm, threading.Lock()
        self.calls: deque[float] = deque()

    def wait(self):
        while True:
            with self.lock:
                now = time.monotonic()
                while self.calls and now - self.calls[0] > 60:
                    self.calls.popleft()
                if len(self.calls) < self.rpm:
                    self.calls.append(now)
                    return
                sleep_for = 60 - (now - self.calls[0])
            time.sleep(max(sleep_for, 0.1))


class Provider:
    def __init__(self, name: str, base_url: str, api_key: str, model: str, rpm: int):
        self.name, self.model = name, model
        self.client = OpenAI(base_url=base_url, api_key=api_key or "none", timeout=settings.request_timeout)
        self.limiter = RateLimiter(rpm)

    def chat(self, messages: list[ChatCompletionMessageParam], temperature: float = 0.4, max_tokens: int = 1000) -> str:
        self.limiter.wait()
        r = self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=temperature, max_tokens=max_tokens
        )
        return r.choices[0].message.content or ""


def build_providers() -> list[Provider]:
    available = {}
    if settings.nvidia_api_key:
        available["nvidia"] = Provider(
            "nvidia", settings.nvidia_base_url, settings.nvidia_api_key, settings.nvidia_model, settings.nvidia_rpm
        )
    available["ollama"] = Provider("ollama", settings.ollama_base_url, "ollama", settings.ollama_model, settings.ollama_rpm)
    names = [n.strip() for n in settings.provider_order.split(",") if n.strip()]
    return [available[n] for n in names if n in available]


_providers: list[Provider] | None = None


def chat(
    messages: list[ChatCompletionMessageParam], temperature: float = 0.4, max_tokens: int = 1000
) -> tuple[str, str]:
    """Try providers in order; fail over on rate limits, timeouts, connection errors and 5xx."""
    global _providers
    if _providers is None:
        _providers = build_providers()
    errors: list[str] = []
    for p in _providers:
        try:
            return p.chat(messages, temperature, max_tokens), f"{p.name}:{p.model}"
        except (RateLimitError, APIConnectionError, APITimeoutError) as e:
            errors.append(f"{p.name}: {type(e).__name__}")
        except APIStatusError as e:
            if e.status_code >= 500:
                errors.append(f"{p.name}: HTTP {e.status_code}")
            else:  # 401/404 etc. are config mistakes; surface them
                raise LLMError(f"{p.name} returned HTTP {e.status_code}: {e.message}") from e
    raise LLMError("All providers failed -> " + "; ".join(errors))
