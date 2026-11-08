"""The interface every LLM client implements, its result and its errors.

A client takes a system prompt, the user content, the pydantic model the reply
must match and a model id. It returns the validated object and the token counts,
or raises an LLMError. Callers never see raw model text.
"""

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

DEFAULT_PARSE_MODEL = "claude-haiku-5-5"
DEFAULT_REWRITE_MODEL = "claude-sonnet-5-5"

OutputT = TypeVar("OutputT", bound=BaseModel)


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class LLMResult(Generic[OutputT]):
    output: OutputT
    usage: Usage
    model: str


class LLMError(Exception):
    """A call that didn't produce a usable answer.

    `reason` is a short code that is safe to store and show. Messages never
    contain prompt text, resume text or the API key.
    """

    reason = "api_error"


class LLMTimeoutError(LLMError):
    reason = "timeout"


class LLMOutputError(LLMError):
    """The model answered, but not with output that matches the schema."""

    reason = "invalid_output"


class LLMClient(Protocol):
    def generate(
        self,
        *,
        system: str,
        user: str,
        output_type: type[OutputT],
        model: str,
        prompt_version: str,
        max_tokens: int = 2048,
    ) -> LLMResult[OutputT]:
        """Ask the model for one object of `output_type`."""
        ...
