from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from adk.planner_executor.config import PlannerExecutorConfig
from adk.planner_executor.nodes import (
    PlanThenActExecutionCoordinator,
    draft_state_update,
)
from adk.planner_executor.state import PlanThenActStep


class _FakeExecutor:
    def __init__(self, executor_id: str, *, delay: float = 0.0) -> None:
        self.executor_id = executor_id
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    def invoke(self, input: dict[str, Any], config: Any = None) -> dict[str, Any]:
        self.calls.append(input)
        if self.delay:
            time.sleep(self.delay)
        return {
            "observations": [f"[{self.executor_id}] {input['next_tool_name']}"],
            "executed_steps": [{"executor_id": self.executor_id, "tool": input["next_tool_name"]}],
        }


def _step(
    executor_id: str,
    tool_name: str,
    *,
    depends_on: list[int] | None = None,
) -> PlanThenActStep:
    return PlanThenActStep(
        executor_id=executor_id,
        tool_name=tool_name,
        tool_args={"q": tool_name},
        depends_on=depends_on,
    )


def test_invoke_routes_by_explicit_executor_id() -> None:
    fake = _FakeExecutor("search")
    coordinator = PlanThenActExecutionCoordinator({"search": fake})
    steps = [_step("search", "web_search")]

    out = coordinator.invoke({"authorized_steps": steps, "context": {"user": "dave"}})

    assert fake.calls == [
        {
            "next_tool_name": "web_search",
            "next_tool_args": {"q": "web_search"},
            "context": {"user": "dave"},
        },
    ]
    assert out == {
        "observations": ["[search] web_search"],
        "executed_steps": [{"executor_id": "search", "tool": "web_search"}],
    }


def test_invoke_routes_by_tools_by_executor_fallback() -> None:
    fake = _FakeExecutor("search")
    config = PlannerExecutorConfig(tools_by_executor={"search": ("web_search",)})
    coordinator = PlanThenActExecutionCoordinator({"search": fake}, config=config)
    steps = [_step("planner", "web_search")]

    out = coordinator.invoke({"authorized_steps": steps})

    assert fake.calls[0]["next_tool_name"] == "web_search"
    assert out["observations"] == ["[search] web_search"]


def test_invoke_raises_on_unknown_executor_and_tool() -> None:
    coordinator = PlanThenActExecutionCoordinator({})
    steps = [_step("missing", "unknown_tool")]

    with pytest.raises(ValueError, match="no executor found"):
        coordinator.invoke({"authorized_steps": steps})


def test_invoke_raises_before_running_any_step_when_one_step_is_unroutable() -> None:
    fake = _FakeExecutor("search")
    coordinator = PlanThenActExecutionCoordinator({"search": fake})
    steps = [_step("search", "web_search"), _step("missing", "unknown_tool")]

    with pytest.raises(ValueError, match="no executor found"):
        coordinator.invoke({"authorized_steps": steps})

    assert fake.calls == []


def test_invoke_merges_independent_steps_in_step_order_regardless_of_completion_order() -> None:
    slow = _FakeExecutor("slow", delay=0.05)
    fast = _FakeExecutor("fast")
    coordinator = PlanThenActExecutionCoordinator({"slow": slow, "fast": fast})
    steps = [_step("slow", "slow_tool"), _step("fast", "fast_tool")]

    out = coordinator.invoke({"authorized_steps": steps})

    assert out["observations"] == ["[slow] slow_tool", "[fast] fast_tool"]
    assert out["executed_steps"] == [
        {"executor_id": "slow", "tool": "slow_tool"},
        {"executor_id": "fast", "tool": "fast_tool"},
    ]


def test_invoke_runs_dependent_step_only_after_its_dependency_completes() -> None:
    order: list[str] = []

    class _RecordingExecutor(_FakeExecutor):
        def invoke(self, input: dict[str, Any], config: Any = None) -> dict[str, Any]:
            order.append(f"start:{self.executor_id}")
            if self.executor_id == "first":
                time.sleep(0.05)
            result = super().invoke(input, config)
            order.append(f"end:{self.executor_id}")
            return result

    first = _RecordingExecutor("first")
    second = _RecordingExecutor("second")
    coordinator = PlanThenActExecutionCoordinator({"first": first, "second": second})
    steps = [_step("first", "first_tool"), _step("second", "second_tool", depends_on=[0])]

    coordinator.invoke({"authorized_steps": steps})

    assert order == ["start:first", "end:first", "start:second", "end:second"]


def test_invoke_raises_on_dependency_cycle() -> None:
    coordinator = PlanThenActExecutionCoordinator(
        {"a": _FakeExecutor("a"), "b": _FakeExecutor("b")},
    )
    steps = [
        _step("a", "tool_a", depends_on=[1]),
        _step("b", "tool_b", depends_on=[0]),
    ]

    with pytest.raises(ValueError, match="cyclic or unresolved depends_on"):
        coordinator.invoke({"authorized_steps": steps})


def test_invoke_respects_max_workers_cap() -> None:
    lock = threading.Lock()
    active = 0
    max_active = 0

    class _ConcurrencyTrackingExecutor(_FakeExecutor):
        def invoke(self, input: dict[str, Any], config: Any = None) -> dict[str, Any]:
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.02)
            result = super().invoke(input, config)
            with lock:
                active -= 1
            return result

    executors = {f"e{i}": _ConcurrencyTrackingExecutor(f"e{i}") for i in range(3)}
    coordinator = PlanThenActExecutionCoordinator(executors, max_workers=1)
    steps = [_step(f"e{i}", f"tool_{i}") for i in range(3)]

    out = coordinator.invoke({"authorized_steps": steps})

    assert max_active == 1
    assert len(out["observations"]) == 3


def test_draft_state_update_returns_llm_output_as_draft_output() -> None:
    class _FakeLlm:
        def __init__(self) -> None:
            self.payload: dict[str, Any] | None = None

        def invoke(self, payload: dict[str, Any], config: Any = None) -> dict[str, Any]:
            self.payload = payload
            return {"summary": "done"}

    llm = _FakeLlm()
    state = {"task": "research", "context": {"user": "dave"}, "observations": ["obs1"]}

    out = draft_state_update(state, llm, drafter_system="be concise")

    assert out == {"draft_output": {"summary": "done"}, "token_usage": []}
    assert llm.payload == {
        "drafter_system": "be concise",
        "task": "research",
        "context": {"user": "dave"},
        "observations": ["obs1"],
    }


def test_draft_state_update_extracts_usage_into_token_usage() -> None:
    class _FakeLlm:
        def invoke(self, payload: dict[str, Any], config: Any = None) -> dict[str, Any]:
            return {"summary": "done", "usage": {"input_tokens": 12, "output_tokens": 4}}

    out = draft_state_update({"task": "research"}, _FakeLlm(), drafter_system="be concise")

    assert out == {
        "draft_output": {"summary": "done"},
        "token_usage": [{"input_tokens": 12, "output_tokens": 4}],
    }
