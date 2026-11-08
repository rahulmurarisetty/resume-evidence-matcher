"""LLMClient for the Anthropic API, using the official SDK.

Structured output comes from tool use: the request offers one tool whose
input_schema is the output model's JSON schema and forces the model to call it.
The tool input is then validated with the same pydantic model.

Timeouts and retries are the SDK's: each attempt waits at most `timeout_seconds`,
and rate limits, server errors, timeouts and dropped connections are retried up
to `max_retries` times with backoff.

Logs carry the model id, prompt version, token counts and latency. They never
carry prompt text, resume text or the key.
"""

import logging
import time
from typing import TYPE_CHECKING

import anthropic
from anthropic.types import MessageParam, ToolChoiceToolParam, ToolParam, ToolUseBlock
from pydantic import ValidationError

from app.llm.client import (
    LLMError,
    LLMOutputError,
    LLMResult,
    LLMTimeoutError,
    OutputT,
    Usage,
)

if TYPE_CHECKING:  # httpx2 comes with the SDK; only tests pass a client of their own.
    import httpx2

logger = logging.getLogger("app.llm")

TOOL_NAME = "record_output"
DEFAULT_MAX_RETRIES = 2


class AnthropicClient:
    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 30.0,
        max_retries: int = DEFAULT_MAX_RETRIES,
        http_client: "httpx2.Client | None" = None,
    ) -> None:
        # An explicit key means the SDK never reads credentials from the environment.
        self._sdk = anthropic.Anthropic(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
            http_client=http_client,
        )

    @property
    def timeout_seconds(self) -> float:
        timeout = self._sdk.timeout
        assert isinstance(timeout, int | float)
        return float(timeout)

    @property
    def max_retries(self) -> int:
        return self._sdk.max_retries

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
        tool: ToolParam = {
            "name": TOOL_NAME,
            "description": "Record the answer. Call this exactly once with the complete answer.",
            "input_schema": output_type.model_json_schema(),
        }
        tool_choice: ToolChoiceToolParam = {
            "type": "tool",
            "name": TOOL_NAME,
            "disable_parallel_tool_use": True,
        }
        messages: list[MessageParam] = [{"role": "user", "content": user}]
        log_fields: dict[str, object] = {"model": model, "prompt_version": prompt_version}
        started = time.perf_counter()

        def elapsed_ms() -> float:
            return round((time.perf_counter() - started) * 1000, 1)

        try:
            message = self._sdk.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                tools=[tool],
                tool_choice=tool_choice,
            )
        except anthropic.APITimeoutError as exc:
            self._log_failure(log_fields, elapsed_ms(), exc)
            raise LLMTimeoutError("The Anthropic API didn't answer in time.") from exc
        except anthropic.APIStatusError as exc:
            self._log_failure(log_fields, elapsed_ms(), exc)
            raise LLMError(f"The Anthropic API answered with status {exc.status_code}.") from exc
        except anthropic.AnthropicError as exc:
            self._log_failure(log_fields, elapsed_ms(), exc)
            raise LLMError("The Anthropic API couldn't be reached.") from exc

        usage = Usage(
            input_tokens=message.usage.input_tokens, output_tokens=message.usage.output_tokens
        )
        logger.info(
            "llm call",
            extra={
                **log_fields,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "duration_ms": elapsed_ms(),
                "stop_reason": message.stop_reason,
            },
        )

        if message.stop_reason == "max_tokens":
            raise LLMOutputError("The answer was cut off at the token limit.")
        block = next(
            (b for b in message.content if isinstance(b, ToolUseBlock) and b.name == TOOL_NAME),
            None,
        )
        if block is None:
            raise LLMOutputError("The model didn't return structured output.")
        try:
            output = output_type.model_validate(block.input)
        except ValidationError as exc:
            # The validation error names fields, not their values, in this message.
            raise LLMOutputError(
                f"The model's output didn't match the schema ({exc.error_count()} errors)."
            ) from exc
        return LLMResult(output=output, usage=usage, model=message.model)

    @staticmethod
    def _log_failure(fields: dict[str, object], duration_ms: float, exc: Exception) -> None:
        # Only the exception class: SDK messages can quote the response body.
        logger.warning(
            "llm call failed",
            extra={**fields, "duration_ms": duration_ms, "error": type(exc).__name__},
        )
