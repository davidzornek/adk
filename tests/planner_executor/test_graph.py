from __future__ import annotations

from typing import Any

from adk.planner_executor.graph import build_plan_then_act_graph, logical_graph_node_ids
from adk.planner_executor.state import PlanThenActArtifact, PlanThenActStep


class _FakePlanner:
    def __init__(
        self, artifact: PlanThenActArtifact, *, usage: dict[str, Any] | None = None,
    ) -> None:
        self.artifact = artifact
        self.usage = usage

    def invoke(self, input: dict[str, Any], config: Any = None) -> dict[str, Any]:
        out: dict[str, Any] = {"plan_artifact": self.artifact}
        if self.usage is not None:
            out["usage"] = self.usage
        return out


class _FakeExecutor:
    def __init__(self, executor_id: str) -> None:
        self.executor_id = executor_id

    def invoke(self, input: dict[str, Any], config: Any = None) -> dict[str, Any]:
        return {
            "observations": [f"[{self.executor_id}] {input['next_tool_name']}"],
            "executed_steps": [{"executor_id": self.executor_id, "tool": input["next_tool_name"]}],
        }


class _FakeDrafter:
    def __init__(self, *, usage: dict[str, Any] | None = None) -> None:
        self.payload: dict[str, Any] | None = None
        self.usage = usage

    def invoke(self, input: dict[str, Any], config: Any = None) -> dict[str, Any]:
        self.payload = input
        out: dict[str, Any] = {"summary": "done"}
        if self.usage is not None:
            out["usage"] = self.usage
        return out


def _build_graph(drafter: _FakeDrafter, *, planner: _FakePlanner | None = None) -> Any:
    artifact = PlanThenActArtifact(
        steps=[PlanThenActStep(executor_id="search", tool_name="web_search", tool_args={"q": "x"})],
    )
    return build_plan_then_act_graph(
        planner=planner or _FakePlanner(artifact),
        executors={"search": _FakeExecutor("search")},
        drafter=drafter,
        drafter_system="be concise",
    )


def test_build_plan_then_act_graph_includes_draft_response_node() -> None:
    compiled = _build_graph(_FakeDrafter())

    assert "draft_response" in logical_graph_node_ids(compiled)


def test_build_plan_then_act_graph_populates_draft_output_from_drafter() -> None:
    compiled = _build_graph(_FakeDrafter())

    out = compiled.invoke({"task": "research", "context": {"user": "dave"}})

    assert out["draft_output"] == {"summary": "done"}


def test_build_plan_then_act_graph_accumulates_token_usage_from_planner_and_drafter() -> None:
    artifact = PlanThenActArtifact(
        steps=[PlanThenActStep(executor_id="search", tool_name="web_search", tool_args={"q": "x"})],
    )
    planner = _FakePlanner(artifact, usage={"input_tokens": 100, "output_tokens": 20})
    drafter = _FakeDrafter(usage={"input_tokens": 5, "output_tokens": 15})
    compiled = _build_graph(drafter, planner=planner)

    out = compiled.invoke({"task": "research", "context": {"user": "dave"}})

    assert out["token_usage"] == [
        {"input_tokens": 100, "output_tokens": 20},
        {"input_tokens": 5, "output_tokens": 15},
    ]


def test_build_plan_then_act_graph_passes_execute_plan_observations_to_drafter() -> None:
    drafter = _FakeDrafter()
    compiled = _build_graph(drafter)

    compiled.invoke({"task": "research", "context": {"user": "dave"}})

    assert drafter.payload == {
        "drafter_system": "be concise",
        "task": "research",
        "context": {"user": "dave"},
        "observations": ["[search] web_search"],
    }
