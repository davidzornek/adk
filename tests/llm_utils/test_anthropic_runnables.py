from __future__ import annotations

import types
from typing import Any

from llm_utils.anthropic_runnables import AnthropicRunnable


class _FakeMessages:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._response


class _FakeAnthropicClient:
    def __init__(self, response: Any) -> None:
        self.messages = _FakeMessages(response)


def _response(*blocks: Any) -> Any:
    return types.SimpleNamespace(content=list(blocks))


def _text_block(text: str) -> Any:
    return types.SimpleNamespace(type="text", text=text)


def _tool_use_block(name: str, input_payload: dict[str, Any]) -> Any:
    return types.SimpleNamespace(type="tool_use", name=name, input=input_payload)


def test_invoke_calls_messages_create_without_tools_by_default() -> None:
    client = _FakeAnthropicClient(_response(_text_block("hello")))
    runnable = AnthropicRunnable(client, model="claude-test", system_prompt="be helpful")  # type: ignore[arg-type]

    runnable.invoke({"task": "greet"})

    assert len(client.messages.calls) == 1
    call = client.messages.calls[0]
    assert call["model"] == "claude-test"
    assert call["system"] == "be helpful"
    assert "greet" in call["messages"][0]["content"]
    assert "tools" not in call
    assert "tool_choice" not in call


def test_invoke_default_parser_returns_text_and_tool_calls() -> None:
    client = _FakeAnthropicClient(
        _response(_text_block("here's the plan"), _tool_use_block("output_plan", {"steps": []})),
    )
    runnable = AnthropicRunnable(client, model="claude-test", system_prompt="plan things")  # type: ignore[arg-type]

    result = runnable.invoke({"task": "plan x"})

    assert result == {
        "text": "here's the plan",
        "tool_calls": [{"name": "output_plan", "input": {"steps": []}}],
    }


def test_invoke_passes_configured_tools_and_tool_choice() -> None:
    client = _FakeAnthropicClient(_response(_tool_use_block("output_plan", {"steps": []})))
    tools = [{"name": "output_plan", "description": "d", "input_schema": {"type": "object"}}]
    tool_choice = {"type": "tool", "name": "output_plan"}
    runnable = AnthropicRunnable(
        client,  # type: ignore[arg-type]
        model="claude-test",
        system_prompt="plan things",
        tools=tools,  # type: ignore[arg-type]
        tool_choice=tool_choice,  # type: ignore[arg-type]
    )

    runnable.invoke({"task": "plan x"})

    call = client.messages.calls[0]
    assert call["tools"] == tools
    assert call["tool_choice"] == tool_choice


def test_invoke_uses_custom_response_parser() -> None:
    client = _FakeAnthropicClient(_response(_text_block("ignored")))
    runnable = AnthropicRunnable(
        client,  # type: ignore[arg-type]
        model="claude-test",
        system_prompt="be helpful",
        response_parser=lambda response: {"custom": True},
    )

    result = runnable.invoke({"task": "greet"})

    assert result == {"custom": True}
