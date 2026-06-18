"""LLM client abstractions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from loguru import logger

from buratino.models.errors import RepositoryError

CONTEXT_OVERFLOW_PATTERNS = (
    "context_length_exceeded",
    "maximum context length",
    "context window",
    "available context size",
    "exceeds the available context size",
    "too many tokens",
    "token limit",
    "prompt is too long",
    "input is too long",
    "request too large",
)


class LlmClient(Protocol):
    def generate_json(self, *, model: str, prompt: str) -> str:
        """Return raw JSON text from an LLM."""


@dataclass
class LiteLlmClient:
    """Thin LiteLLM adapter."""

    api_base: str | None = None
    api_key: str | None = None
    timeout_seconds: float = 120.0
    temperature: float = 0.0
    max_tokens: int | None = None

    def generate_json(self, *, model: str, prompt: str) -> str:
        try:
            from litellm import completion
        except ImportError as exc:  # pragma: no cover - dependency issue only
            raise RepositoryError("litellm is not installed.") from exc

        kwargs: dict[str, object] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "timeout": self.timeout_seconds,
        }
        if self.api_base is not None:
            kwargs["api_base"] = self.api_base
        if self.api_key is not None:
            kwargs["api_key"] = self.api_key
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens

        try:
            logger.debug("LLM request: model={} prompt_chars={}", model, len(prompt))
            response = completion(**kwargs)
        except Exception as exc:  # pragma: no cover - transport/external system failure
            raise RepositoryError(f"LLM request failed: {exc}") from exc

        try:
            content = str(response.choices[0].message.content).strip()
            logger.debug("LLM response: model={} response_chars={}", model, len(content))
            return content
        except Exception as exc:  # pragma: no cover - external response shape
            raise RepositoryError("LLM response does not contain message content.") from exc


def is_context_overflow_error(exc: Exception) -> bool:
    seen: set[int] = set()
    messages: list[str] = []
    current: Exception | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        rendered = str(current).strip().lower()
        if rendered:
            messages.append(rendered)
        current = current.__cause__ or current.__context__
    combined = " ".join(messages)
    return any(pattern in combined for pattern in CONTEXT_OVERFLOW_PATTERNS)
