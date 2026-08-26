"""Text LLM boundary. The SDK import stays inside the call so tests never need it."""

from __future__ import annotations

import os
from typing import Any, List

DEFAULT_MODEL = "claude-sonnet-5"
# a 25-article batch answers with 25 objects of summary plus evidence, so the
# reply is far longer than the prompt-shaped defaults elsewhere
MAX_TOKENS = 8192
RETRYABLE_STATUS = (408, 409, 429)
RETRYABLE_NAMES = (
    "timeout",
    "connection",
    "ratelimit",
    "overloaded",
    "internalserver",
)


class LLMNotConfigured(Exception):
    """No usable text provider: missing API key or missing SDK."""


class LLMError(Exception):
    """The provider call failed. `retryable` marks transient failures."""

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def is_retryable(err: BaseException) -> bool:
    """Timeouts, rate limits and server errors are worth another attempt."""
    status = getattr(err, "status_code", None)
    if isinstance(status, int):
        return status in RETRYABLE_STATUS or status >= 500
    name = type(err).__name__.lower()
    return any(token in name for token in RETRYABLE_NAMES)


def text_of(message: Any) -> str:
    """Join the text blocks of an Anthropic message into one string."""
    parts: List[str] = []
    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
    return "".join(parts).strip()


class AnthropicText:
    """Anthropic Messages API text generation.

    Thinking is disabled: every call here asks for one strict JSON document that
    is validated against a schema, and a thinking preamble only adds latency and
    tokens to a reply the parser throws away.
    """

    def __init__(self, model: str = "", max_tokens: int = MAX_TOKENS) -> None:
        self.model = model or os.environ.get("JANUSLINE_MODEL") or DEFAULT_MODEL
        self.max_tokens = max_tokens

    def generate(self, system: str, user: str) -> str:
        client = self._client()
        try:
            message = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                thinking={"type": "disabled"},
                messages=[{"role": "user", "content": user}],
            )
        except Exception as err:  # provider failures are normalised for the API layer
            raise LLMError(
                f"{type(err).__name__}: {err}", retryable=is_retryable(err)
            ) from err
        text = text_of(message)
        if not text:
            raise LLMError("empty response from model", retryable=True)
        return text

    @staticmethod
    def _client() -> Any:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMNotConfigured("ANTHROPIC_API_KEY is not set")
        try:
            import anthropic
        except ImportError as err:
            raise LLMNotConfigured("the anthropic package is not installed") from err
        return anthropic.Anthropic(api_key=api_key)
