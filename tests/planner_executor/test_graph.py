from __future__ import annotations

from typing import Any

from adk.planner_executor.graph import build_plan_then_act_graph, logical_graph_node_ids
from adk.planner_executor.state import PlanThenActArtifact, PlanThenActStep


class _FakePlanner:
    def __init__(self, artifact: PlanThenActArtifact) -> None:
        self.artifact = artifact

    def invoke(self, input: dict[str, Any], config: Any = None) -> dict[str, Any]:
        return {"plan_artifact": self.artifact}


class _FakeExecutor:
    def __init__(self, executor_id: str) -> None:
        self.executor_id = executor_id

    def invoke(self, input: dict[str, Any], config: Any = None) -> dict[str, Any]:
        return {
            "observations": [f"[{self.executor_id}] {input['next_tool_name']}"],
            "executed_steps": [{"executor_id": self.executor_id, "tool": input["next_tool_name"]}],
        }


class _FakeDrafter:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None

    def invoke(self, input: dict[str, Any], config: Any = None) -> dict[str, Any]:
        self.payload = input
        return {"summary": "done"}


def _build_graph(drafter: _FakeDrafter) -> Any:
    artifact = PlanThenActArtifact(
        steps=[PlanThenActStep(executor_id="search", tool_name="web_search", tool_args={"q": "x"})],
    )
    return build_plan_then_act_graph(
        planner=_FakePlanner(artifact),
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
