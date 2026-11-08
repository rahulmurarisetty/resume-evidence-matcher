"""Calls to Claude: the client interface, the Anthropic implementation and the
versioned prompts. Nothing here runs unless a key is configured."""

import logging

from app.errors import StartupError
from app.llm.client import (
    LLMClient,
    LLMError,
    LLMOutputError,
    LLMResult,
    LLMTimeoutError,
    Usage,
)

__all__ = [
    "LLMClient",
    "LLMError",
    "LLMOutputError",
    "LLMResult",
    "LLMTimeoutError",
    "Usage",
    "start_llm",
]

logger = logging.getLogger("app.llm")


def start_llm(enabled: str, api_key: str | None, *, timeout_seconds: float) -> LLMClient | None:
    """The client to use, or None when Claude is off.

    "auto" turns it on only when a key is set. "on" without a key stops the app
    at startup. The key is never put in an error message.
    """
    if enabled == "off":
        return None
    if not api_key:
        if enabled == "on":
            raise StartupError(
                "LLM_ENABLED=on needs ANTHROPIC_API_KEY. Set it in the environment or a "
                "local .env file, or set LLM_ENABLED=off."
            )
        return None
    from app.llm.anthropic_client import AnthropicClient

    return AnthropicClient(api_key, timeout_seconds=timeout_seconds)
