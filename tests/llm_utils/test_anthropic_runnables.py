from __future__ import annotations

import types
from typing import Any

import pytest

from llm_utils.anthropic_runnables import _SUBMIT_PLAN_TOOL, AnthropicRunnable
from llm_utils.planner_executor.state import PlanThenActArtifact, PlanThenActStep


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


def _tool_use_response(input_payload: dict[str, Any]) -> Any:
    block = types.SimpleNamespace(type="tool_use", name="submit_plan", input=input_payload)
    return types.SimpleNamespace(content=[block])


def test_invoke_forces_submit_plan_tool_use() -> None:
    steps = [{"executor_id": "search", "tool_name": "web_search", "tool_args": {"q": "x"}}]
    client = _FakeAnthropicClient(_tool_use_response({"steps": steps}))
    runnable = AnthropicRunnable(client, model="claude-test", system_prompt="be a planner")  # type: ignore[arg-type]

    runnable.invoke({"task": "research x"})

    assert len(client.messages.calls) == 1
    call = client.messages.calls[0]
    assert call["model"] == "claude-test"
    assert call["system"] == "be a planner"
    assert "research x" in call["messages"][0]["content"]
    assert call["tools"] == [_SUBMIT_PLAN_TOOL]
    assert call["tool_choice"] == {"type": "tool", "name": "submit_plan"}


def test_invoke_returns_plan_artifact_parsed_from_tool_use() -> None:
    steps = [{"executor_id": "search", "tool_name": "web_search", "tool_args": {"q": "x"}}]
    client = _FakeAnthropicClient(_tool_use_response({"steps": steps}))
    runnable = AnthropicRunnable(client, model="claude-test", system_prompt="be a planner")  # type: ignore[arg-type]

    result = runnable.invoke({"task": "research x"})

    assert result == {
        "plan_artifact": PlanThenActArtifact(
            steps=[
                PlanThenActStep(
                    executor_id="search",
                    tool_name="web_search",
                    tool_args={"q": "x"},
                ),
            ],
        ),
    }


def test_invoke_raises_when_no_submit_plan_tool_use_block() -> None:
    text_block = types.SimpleNamespace(type="text", text="I refuse")
    client = _FakeAnthropicClient(types.SimpleNamespace(content=[text_block]))
    runnable = AnthropicRunnable(client, model="claude-test", system_prompt="be a planner")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="submit_plan"):
        runnable.invoke({"task": "research x"})


def test_submit_plan_tool_schema_matches_artifact() -> None:
    assert _SUBMIT_PLAN_TOOL["name"] == "submit_plan"
    assert _SUBMIT_PLAN_TOOL["input_schema"] == PlanThenActArtifact.model_json_schema()
