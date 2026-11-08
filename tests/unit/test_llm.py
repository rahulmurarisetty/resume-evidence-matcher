"""The LLM layer: prompt files, settings, startup, and the Anthropic client.

The client tests run the real SDK against httpx2's MockTransport, so the request
it builds and the response it parses are the SDK's own. Nothing leaves the
machine.
"""

import contextlib
import json
import logging
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.llm import LLMError, LLMOutputError, LLMTimeoutError, start_llm
from app.llm.anthropic_client import TOOL_NAME, AnthropicClient
from app.llm.prompts import JD_PARSE, REWRITE, load_prompt
from app.logging_setup import configure_logging
from app.main import start_claude

ROOT = Path(__file__).resolve().parents[2]
KEY = "sk-ant-test-0123456789-NOT-A-REAL-KEY"


class Answer(BaseModel):
    rewrites: list[str]


def _settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


# -- prompts -------------------------------------------------------------------


def test_prompts_are_versioned_files() -> None:
    for name, version in (JD_PARSE, REWRITE):
        prompt = load_prompt(name, version)
        assert prompt.id == f"{name}_v{version}"
        assert (ROOT / "app" / "llm" / "prompts" / f"{prompt.id}.md").is_file()
        assert len(prompt.text) > 200
        assert "record_output" in prompt.text


def test_prompt_files_ship_with_the_package() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]["app"]
    assert "llm/prompts/*.md" in package_data
    assert "anthropic" in " ".join(pyproject["project"]["dependencies"])


def test_missing_prompt_fails() -> None:
    with pytest.raises(FileNotFoundError):
        load_prompt("no_such_prompt", 1)


# -- settings and startup --------------------------------------------------------


def test_llm_settings() -> None:
    settings = _settings(llm_enabled=" ON ", anthropic_api_key=KEY)
    assert settings.llm_enabled == "on"
    assert settings.llm_parse_model == "claude-haiku-5-5"
    assert settings.llm_rewrite_model == "claude-sonnet-5-5"
    assert settings.llm_max_suggestions == 20
    assert KEY not in repr(settings)
    assert KEY not in str(settings.model_dump())
    with pytest.raises(ValidationError):
        _settings(llm_enabled="sometimes")


def test_blank_key_means_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _settings(anthropic_api_key="  ").anthropic_api_key is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert _settings().anthropic_api_key is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    key = _settings().anthropic_api_key
    assert key is not None and key.get_secret_value() == KEY


def test_start_llm_modes() -> None:
    assert start_llm("off", KEY, timeout_seconds=5) is None
    assert start_llm("auto", None, timeout_seconds=5) is None
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY") as error:
        start_llm("on", None, timeout_seconds=5)
    assert KEY not in str(error.value)
    client = start_llm("auto", KEY, timeout_seconds=7.5)
    assert isinstance(client, AnthropicClient)
    assert client.timeout_seconds == 7.5
    assert client.max_retries == 2


def test_start_claude_reads_settings() -> None:
    assert start_claude(_settings(llm_enabled="auto")) is None
    client = start_claude(_settings(anthropic_api_key=KEY, llm_timeout_seconds=12))
    assert isinstance(client, AnthropicClient)
    assert client.timeout_seconds == 12


# -- the Anthropic client ----------------------------------------------------------


def _message(content: list[dict[str, Any]], stop_reason: str = "tool_use") -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 321, "output_tokens": 54},
    }


def _tool_use(payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": "toolu_test", "name": TOOL_NAME, "input": payload}


def _client(
    responses: list[httpx2.Response | Exception], max_retries: int = 0
) -> tuple[AnthropicClient, list[httpx2.Request]]:
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    transport = httpx2.MockTransport(handler)
    client = AnthropicClient(
        KEY,
        timeout_seconds=12.5,
        max_retries=max_retries,
        http_client=httpx2.Client(transport=transport),
    )
    return client, sent


def _generate(client: AnthropicClient) -> Any:
    return client.generate(
        system="SYSTEM PROMPT TEXT",
        user="<bullet>Built PRIVATE-RESUME-LINE dashboards</bullet>",
        output_type=Answer,
        model="claude-sonnet-5-5",
        prompt_version="rewrite_v1",
        max_tokens=512,
    )


def test_request_forces_one_tool_with_the_output_schema() -> None:
    reply = httpx2.Response(200, json=_message([_tool_use({"rewrites": ["Built dashboards"]})]))
    client, sent = _client([reply])
    result = _generate(client)

    [request] = sent
    assert request.method == "POST"
    assert request.url.path == "/v1/messages"
    assert KEY in request.headers["authorization"]
    body = json.loads(request.content)
    assert body["model"] == "claude-sonnet-5-5"
    assert body["max_tokens"] == 512
    assert body["system"] == "SYSTEM PROMPT TEXT"
    assert body["messages"] == [
        {"role": "user", "content": "<bullet>Built PRIVATE-RESUME-LINE dashboards</bullet>"}
    ]
    [tool] = body["tools"]
    assert tool["name"] == TOOL_NAME
    assert tool["input_schema"] == Answer.model_json_schema()
    assert body["tool_choice"] == {
        "type": "tool",
        "name": TOOL_NAME,
        "disable_parallel_tool_use": True,
    }

    assert result.output == Answer(rewrites=["Built dashboards"])
    assert (result.usage.input_tokens, result.usage.output_tokens) == (321, 54)
    assert result.model == "claude-sonnet-5-5"


def test_text_before_the_tool_call_is_ignored() -> None:
    reply = _message([{"type": "text", "text": "Here you go."}, _tool_use({"rewrites": []})])
    client, _ = _client([httpx2.Response(200, json=reply)])
    assert _generate(client).output == Answer(rewrites=[])


def test_transient_errors_are_retried() -> None:
    overloaded = httpx2.Response(
        529,
        headers={"retry-after-ms": "1"},
        json={"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}},
    )
    reply = httpx2.Response(200, json=_message([_tool_use({"rewrites": ["x"]})]))
    client, sent = _client([overloaded, reply], max_retries=1)
    assert _generate(client).output.rewrites == ["x"]
    assert len(sent) == 2


def test_timeout_raises_llm_timeout() -> None:
    client, _ = _client([httpx2.ReadTimeout("slow")])
    with pytest.raises(LLMTimeoutError) as error:
        _generate(client)
    assert error.value.reason == "timeout"


def test_connection_error_raises_llm_error() -> None:
    client, _ = _client([httpx2.ConnectError("refused")])
    with pytest.raises(LLMError, match="couldn't be reached") as error:
        _generate(client)
    assert error.value.reason == "api_error"


@pytest.mark.parametrize("status", [400, 401, 500])
def test_api_errors_never_quote_the_key_or_body(status: int) -> None:
    body = {"type": "error", "error": {"type": "x", "message": f"bad request {KEY}"}}
    client, _ = _client([httpx2.Response(status, json=body)])
    with pytest.raises(LLMError) as error:
        _generate(client)
    assert error.value.reason == "api_error"
    assert str(status) in str(error.value)
    assert KEY not in str(error.value)


@pytest.mark.parametrize(
    "reply",
    [
        _message([_tool_use({"rewrites": "not a list"})]),
        _message([{"type": "text", "text": "I can't help with that."}], stop_reason="end_turn"),
        _message([_tool_use({"rewrites": ["cut off"]})], stop_reason="max_tokens"),
    ],
    ids=["schema", "no-tool-call", "max-tokens"],
)
def test_unusable_output_raises_output_error(reply: dict[str, Any]) -> None:
    client, _ = _client([httpx2.Response(200, json=reply)])
    with pytest.raises(LLMOutputError) as error:
        _generate(client)
    assert error.value.reason == "invalid_output"


def _capture(caplog: pytest.LogCaptureFixture, level: str) -> None:
    configure_logging(level)
    # configure_logging replaces the root handlers, caplog's included.
    logging.getLogger().addHandler(caplog.handler)
    caplog.handler.setLevel(logging.DEBUG)


def _run_logged(
    caplog: pytest.LogCaptureFixture, call: Callable[[], object]
) -> list[logging.LogRecord]:
    with contextlib.suppress(LLMError):
        call()
    return list(caplog.records)


def test_logs_have_counts_but_no_text_or_key(caplog: pytest.LogCaptureFixture) -> None:
    _capture(caplog, "DEBUG")
    reply = httpx2.Response(200, json=_message([_tool_use({"rewrites": ["Built dashboards"]})]))
    client, _ = _client([reply])
    records = _run_logged(caplog, lambda: _generate(client))

    call = next(r for r in records if r.getMessage() == "llm call")
    assert call.__dict__["model"] == "claude-sonnet-5-5"
    assert call.__dict__["prompt_version"] == "rewrite_v1"
    assert call.__dict__["input_tokens"] == 321
    assert call.__dict__["output_tokens"] == 54
    assert call.__dict__["duration_ms"] >= 0
    # The SDK logs request bodies at DEBUG; configure_logging keeps it quiet.
    assert not [r for r in records if r.name.startswith(("anthropic", "httpx"))]
    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in records)
    assert "PRIVATE-RESUME-LINE" not in text
    assert "SYSTEM PROMPT TEXT" not in text
    assert KEY not in text
    configure_logging("WARNING")


def test_failure_logs_name_the_error_only(caplog: pytest.LogCaptureFixture) -> None:
    _capture(caplog, "INFO")
    body = {"type": "error", "error": {"type": "x", "message": "PRIVATE-RESUME-LINE"}}
    client, _ = _client([httpx2.Response(401, json=body)])
    records = _run_logged(caplog, lambda: _generate(client))
    failed = next(r for r in records if r.getMessage() == "llm call failed")
    assert failed.__dict__["error"] == "AuthenticationError"
    assert failed.exc_info is None
    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in records)
    assert "PRIVATE-RESUME-LINE" not in text and KEY not in text
    configure_logging("WARNING")
