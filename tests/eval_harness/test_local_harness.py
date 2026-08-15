from __future__ import annotations

from typing import Any

from adk.eval_harness.cases import EvalCase, ExpectedStep, RunResult
from adk.eval_harness.local_harness import rollup, run_and_score
from adk.eval_harness.metrics import plan_execution_alignment, steps_to_completion, task_success


class _FakeAgent:
    """Records inputs and returns pre-built outputs keyed by task; no real graph/API calls."""

    def __init__(self, outputs_by_task: dict[str, dict[str, Any]]) -> None:
        self._outputs_by_task = outputs_by_task
        self.invoked_with: list[dict[str, Any]] = []

    def invoke(self, input: dict[str, Any]) -> dict[str, Any]:
        self.invoked_with.append(input)
        return self._outputs_by_task[input["task"]]

    def to_eval_run_result(
        self,
        out: dict[str, Any],
        *,
        case_id: str,
        output: Any = None,
    ) -> RunResult:
        trace = out["invoke_trace"]
        return RunResult(
            case_id=case_id,
            run_id=trace["run_id"],
            output=output,
            metadata=trace,
            executed_steps=out.get("executed_steps"),
        )


def _out(
    run_id: str,
    executed_steps: list[dict[str, Any]],
    *,
    draft_output: str = "done",
) -> dict[str, Any]:
    return {
        "draft_output": draft_output,
        "executed_steps": executed_steps,
        "invoke_trace": {"run_id": run_id, "latency_ms": 10.0, "tokens_in": 5, "tokens_out": 7},
    }


def test_run_and_score_merges_case_id_run_id_and_metric_outputs() -> None:
    case = EvalCase(
        id="c1",
        task="do x",
        expected_steps=[ExpectedStep(executor_id="search", tool_name="web_search")],
    )
    out = _out("run-1", [{"executor_id": "search", "tool": "web_search", "status": "ok"}])
    agent = _FakeAgent({"do x": out})

    rows = run_and_score(
        [case], agent, [task_success, steps_to_completion, plan_execution_alignment],
    )

    assert rows == [
        {
            "case_id": "c1",
            "run_id": "run-1",
            "success": True,
            "n_steps": 1,
            "n_degraded_steps": 0,
            "degraded_step_indices": [],
            "steps_to_completion": 1,
            "aligned": True,
            "n_expected_steps": 1,
            "n_executed_steps": 1,
            "mismatches": [],
        },
    ]


def test_run_and_score_invokes_agent_with_task_and_context() -> None:
    case = EvalCase(id="c1", task="do x", context={"k": "v"})
    agent = _FakeAgent({"do x": _out("run-1", [])})

    run_and_score([case], agent, [])

    assert agent.invoked_with == [{"task": "do x", "context": {"k": "v"}}]


def test_run_and_score_with_no_metrics_returns_bare_identifiers() -> None:
    case = EvalCase(id="c1", task="do x")
    agent = _FakeAgent({"do x": _out("run-1", [])})

    rows = run_and_score([case], agent, [])

    assert rows == [{"case_id": "c1", "run_id": "run-1"}]


def test_rollup_computes_pass_rate_avg_steps_and_alignment_rate() -> None:
    rows = [
        {"success": True, "steps_to_completion": 2, "aligned": True},
        {"success": False, "steps_to_completion": 4, "aligned": False},
    ]

    out = rollup(rows)

    assert out == {
        "n_cases": 2,
        "pass_rate": 0.5,
        "avg_steps_to_completion": 3.0,
        "alignment_rate": 0.5,
    }


def test_rollup_omits_aggregates_for_metrics_not_present() -> None:
    rows = [{"steps_to_completion": 2}, {"steps_to_completion": 4}]

    out = rollup(rows)

    assert out == {"n_cases": 2, "avg_steps_to_completion": 3.0}


def test_rollup_of_empty_rows() -> None:
    assert rollup([]) == {"n_cases": 0}
