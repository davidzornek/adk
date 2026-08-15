from __future__ import annotations

import types
from typing import Any

import pytest

from llm_utils.planner_executor.planner import _OUTPUT_PLAN_TOOL, build_plan_then_act_planner
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
    block = types.SimpleNamespace(type="tool_use", name="output_plan", input=input_payload)
    return types.SimpleNamespace(content=[block])


def test_build_plan_then_act_planner_forces_output_plan_tool_use() -> None:
    steps = [{"executor_id": "search", "tool_name": "web_search", "tool_args": {"q": "x"}}]
    client = _FakeAnthropicClient(_tool_use_response({"steps": steps}))
    planner = build_plan_then_act_planner(client, model="claude-test", system_prompt="plan it")  # type: ignore[arg-type]

    planner.invoke({"task": "research x"})

    call = client.messages.calls[0]
    assert call["tools"] == [_OUTPUT_PLAN_TOOL]
    assert call["tool_choice"] == {"type": "tool", "name": "output_plan"}


def test_build_plan_then_act_planner_returns_parsed_plan_artifact() -> None:
    steps = [{"executor_id": "search", "tool_name": "web_search", "tool_args": {"q": "x"}}]
    client = _FakeAnthropicClient(_tool_use_response({"steps": steps}))
    planner = build_plan_then_act_planner(client, model="claude-test", system_prompt="plan it")  # type: ignore[arg-type]

    result = planner.invoke({"task": "research x"})

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


def test_build_plan_then_act_planner_raises_when_no_output_plan_tool_use_block() -> None:
    text_block = types.SimpleNamespace(type="text", text="I refuse")
    client = _FakeAnthropicClient(types.SimpleNamespace(content=[text_block]))
    planner = build_plan_then_act_planner(client, model="claude-test", system_prompt="plan it")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="output_plan"):
        planner.invoke({"task": "research x"})


def test_output_plan_tool_schema_matches_artifact() -> None:
    assert _OUTPUT_PLAN_TOOL["name"] == "output_plan"
    assert _OUTPUT_PLAN_TOOL["input_schema"] == PlanThenActArtifact.model_json_schema()
