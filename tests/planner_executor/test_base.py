from __future__ import annotations

from typing import Any

from adk.planner_executor.base import INVOKE_TRACE_KEY, PlannerExecutorBase
from adk.planner_executor.config import PlannerExecutorConfig
from adk.planner_executor.graph import build_plan_then_act_graph
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
            "executed_steps": [
                {"executor_id": self.executor_id, "tool": input["next_tool_name"]},
            ],
        }


class _FakeDrafter:
    def invoke(self, input: dict[str, Any], config: Any = None) -> dict[str, Any]:
        return {"summary": "done"}


class _DemoAgent(PlannerExecutorBase):
    """Minimal concrete subclass wired to a real (fake-Runnable) compiled graph."""

    @property
    def variant(self) -> str:
        return "plan_then_act"

    def _input_to_state(self, input: dict[str, Any]) -> dict[str, Any]:
        return {"task": input["task"], "context": input.get("context", {})}

    def _build_graph(self) -> Any:
        artifact = PlanThenActArtifact(
            steps=[
                PlanThenActStep(executor_id="search", tool_name="web_search", tool_args={"q": "x"}),
            ],
        )
        return build_plan_then_act_graph(
            planner=_FakePlanner(artifact),
            executors={"search": _FakeExecutor("search")},
            drafter=_FakeDrafter(),
            drafter_system="be concise",
        )


def test_constructor_defaults() -> None:
    agent = _DemoAgent()

    assert agent.config.tools_by_executor == {}
    assert agent._prompt_manifest == {}


def test_constructor_accepts_config_and_prompt_manifest() -> None:
    config = PlannerExecutorConfig(tools_by_executor={"search": ("web_search",)})

    agent = _DemoAgent(config=config, prompt_manifest={"planner": "v1"})

    assert agent.config is config
    assert agent._prompt_manifest == {"planner": "v1"}


def test_invoke_attaches_invoke_trace() -> None:
    agent = _DemoAgent()

    out = agent.invoke({"task": "research", "context": {}, "session_label": "sess-1"})

    trace = out[INVOKE_TRACE_KEY]
    assert set(trace) == {"run_id", "variant", "session_label", "prompt_manifest"}
    assert trace["variant"] == "plan_then_act"
    assert trace["session_label"] == "sess-1"
    assert trace["prompt_manifest"] == {}
    assert isinstance(trace["run_id"], str) and trace["run_id"]


def test_invoke_omits_session_label_when_absent_from_input() -> None:
    agent = _DemoAgent()

    out = agent.invoke({"task": "research", "context": {}})

    assert out[INVOKE_TRACE_KEY]["session_label"] is None


def test_invoke_generates_a_fresh_run_id_per_call() -> None:
    agent = _DemoAgent()

    out1 = agent.invoke({"task": "a", "context": {}})
    out2 = agent.invoke({"task": "b", "context": {}})

    assert out1[INVOKE_TRACE_KEY]["run_id"] != out2[INVOKE_TRACE_KEY]["run_id"]


def test_stream_attaches_invoke_trace_only_to_final_update() -> None:
    agent = _DemoAgent()

    updates = list(agent.stream({"task": "research", "context": {}}))

    assert len(updates) >= 2
    for update in updates[:-1]:
        assert INVOKE_TRACE_KEY not in update
    assert updates[-1][INVOKE_TRACE_KEY]["variant"] == "plan_then_act"


def test_invoke_trace_metadata_round_trips_off_invoke_output() -> None:
    agent = _DemoAgent()
    out = agent.invoke({"task": "research", "context": {}})

    assert PlannerExecutorBase.invoke_trace_metadata(out) == out[INVOKE_TRACE_KEY]


def test_invoke_trace_metadata_returns_empty_dict_when_key_missing() -> None:
    assert PlannerExecutorBase.invoke_trace_metadata({}) == {}


def test_get_compiled_graph_exposes_the_compiled_graph() -> None:
    agent = _DemoAgent()

    assert agent.get_compiled_graph() is agent.graph


def test_eval_harness_graph_node_ids_reflects_the_compiled_graph() -> None:
    agent = _DemoAgent()

    assert agent.eval_harness_graph_node_ids() == (
        "produce_plan",
        "execute_plan",
        "draft_response",
    )
