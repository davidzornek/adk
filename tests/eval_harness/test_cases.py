from __future__ import annotations

from adk.eval_harness.cases import EvalCase, ExpectedStep, RunResult


def test_eval_case_defaults() -> None:
    case = EvalCase(id="c1", task="do x")

    assert case.context == {}
    assert case.expected_output is None
    assert case.expected_steps is None


def test_eval_case_accepts_expected_steps() -> None:
    case = EvalCase(
        id="c1",
        task="do x",
        expected_steps=[ExpectedStep(executor_id="search", tool_name="web_search")],
    )

    assert case.expected_steps == [ExpectedStep(executor_id="search", tool_name="web_search")]


def test_run_result_defaults() -> None:
    result = RunResult(case_id="c1")

    assert result.run_id is None
    assert result.output is None
    assert result.metadata == {}
    assert result.executed_steps is None


def test_expected_step_round_trips_executor_id_and_tool_name() -> None:
    step = ExpectedStep(executor_id="calc", tool_name="calculate")

    assert step.executor_id == "calc"
    assert step.tool_name == "calculate"
