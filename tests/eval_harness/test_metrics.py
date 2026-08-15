from __future__ import annotations

from typing import Any

import pytest

from adk.eval_harness.cases import EvalCase, ExpectedStep, RunResult
from adk.eval_harness.metrics import (
    latency,
    plan_adequacy,
    plan_execution_alignment,
    steps_to_completion,
    task_success,
    token_counts,
)


def _executed_step(executor_id: str, tool: str, *, status: str = "ok") -> dict[str, Any]:
    return {"executor_id": executor_id, "tool": tool, "status": status}


def _run_result(
    executed_steps: list[dict[str, Any]] | None = None,
    *,
    metadata: dict[str, Any] | None = None,
) -> RunResult:
    return RunResult(case_id="c1", executed_steps=executed_steps, metadata=metadata or {})


def _case(*, expected_steps: list[ExpectedStep] | None = None) -> EvalCase:
    return EvalCase(id="c1", task="do x", expected_steps=expected_steps)


# task_success


def test_task_success_true_when_no_degraded_steps() -> None:
    result = _run_result(
        [_executed_step("search", "web_search"), _executed_step("calc", "calculate")],
    )

    out = task_success(_case(), result)

    assert out == {
        "success": True,
        "n_steps": 2,
        "n_degraded_steps": 0,
        "degraded_step_indices": [],
    }


def test_task_success_false_when_any_step_degraded() -> None:
    result = _run_result(
        [
            _executed_step("search", "web_search"),
            _executed_step("calc", "calculate", status="degraded"),
        ],
    )

    out = task_success(_case(), result)

    assert out["success"] is False
    assert out["degraded_step_indices"] == [1]


def test_task_success_true_when_no_steps_executed() -> None:
    out = task_success(_case(), _run_result([]))

    assert out == {
        "success": True,
        "n_steps": 0,
        "n_degraded_steps": 0,
        "degraded_step_indices": [],
    }


def test_task_success_raises_when_executed_steps_is_none() -> None:
    with pytest.raises(ValueError, match="executed_steps"):
        task_success(_case(), _run_result(None))


# steps_to_completion


def test_steps_to_completion_counts_all_executed_steps() -> None:
    result = _run_result(
        [
            _executed_step("search", "web_search"),
            _executed_step("calc", "calculate"),
            _executed_step("calc", "calculate", status="degraded"),
        ],
    )

    assert steps_to_completion(_case(), result) == {"steps_to_completion": 3}


def test_steps_to_completion_zero_when_no_steps_executed() -> None:
    assert steps_to_completion(_case(), _run_result([])) == {"steps_to_completion": 0}


def test_steps_to_completion_raises_when_executed_steps_is_none() -> None:
    with pytest.raises(ValueError, match="executed_steps"):
        steps_to_completion(_case(), _run_result(None))


# plan_execution_alignment


def test_plan_execution_alignment_true_when_executed_matches_expected_in_order() -> None:
    case = _case(
        expected_steps=[
            ExpectedStep(executor_id="search", tool_name="web_search"),
            ExpectedStep(executor_id="calc", tool_name="calculate"),
        ],
    )
    result = _run_result(
        [_executed_step("search", "web_search"), _executed_step("calc", "calculate")],
    )

    out = plan_execution_alignment(case, result)

    assert out == {
        "aligned": True,
        "n_expected_steps": 2,
        "n_executed_steps": 2,
        "mismatches": [],
    }


def test_plan_execution_alignment_false_on_genuine_tool_choice_mismatch() -> None:
    case = _case(expected_steps=[ExpectedStep(executor_id="search", tool_name="web_search")])
    result = _run_result([_executed_step("calc", "calculate")])

    out = plan_execution_alignment(case, result)

    assert out["aligned"] is False
    assert out["mismatches"] == [
        {
            "index": 0,
            "expected": {"executor_id": "search", "tool_name": "web_search"},
            "actual": {"executor_id": "calc", "tool": "calculate"},
        },
    ]


def test_plan_execution_alignment_false_when_executed_has_fewer_steps_than_expected() -> None:
    case = _case(
        expected_steps=[
            ExpectedStep(executor_id="search", tool_name="web_search"),
            ExpectedStep(executor_id="calc", tool_name="calculate"),
        ],
    )
    result = _run_result([_executed_step("search", "web_search")])

    out = plan_execution_alignment(case, result)

    assert out["aligned"] is False
    assert out["mismatches"] == [
        {
            "index": 1,
            "expected": {"executor_id": "calc", "tool_name": "calculate"},
            "actual": None,
        },
    ]


def test_plan_execution_alignment_raises_when_case_has_no_expected_steps() -> None:
    with pytest.raises(ValueError, match="expected_steps"):
        plan_execution_alignment(_case(), _run_result([_executed_step("search", "web_search")]))


def test_plan_execution_alignment_raises_when_executed_steps_is_none() -> None:
    case = _case(expected_steps=[ExpectedStep(executor_id="search", tool_name="web_search")])

    with pytest.raises(ValueError, match="executed_steps"):
        plan_execution_alignment(case, _run_result(None))


# latency


def test_latency_returns_recorded_value() -> None:
    result = _run_result(metadata={"latency_ms": 123.4})

    assert latency(_case(), result) == {"latency_ms": 123.4}


def test_latency_returns_none_when_not_recorded() -> None:
    assert latency(_case(), _run_result()) == {"latency_ms": None}


# token_counts


def test_token_counts_returns_recorded_totals() -> None:
    result = _run_result(metadata={"tokens_in": 10, "tokens_out": 5})

    assert token_counts(_case(), result) == {
        "tokens_in": 10,
        "tokens_out": 5,
        "tokens_total": 15,
    }


def test_token_counts_returns_none_fields_when_not_recorded() -> None:
    assert token_counts(_case(), _run_result()) == {
        "tokens_in": None,
        "tokens_out": None,
        "tokens_total": None,
    }


# plan_adequacy


def test_plan_adequacy_returns_stub_placeholder() -> None:
    assert plan_adequacy(_case(), _run_result()) == {
        "score": None,
        "rationale": None,
        "stub": True,
    }
