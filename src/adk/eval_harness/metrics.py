"""Pure metric functions matching :data:`~adk.eval_harness.cases.MetricFn`.

Each function takes ``(EvalCase, RunResult)`` and returns a plain dict of descriptive,
per-metric-named fields - no shared "result" envelope, no side effects, no I/O.
"""

from __future__ import annotations

from typing import Any

from adk.eval_harness.cases import EvalCase, RunResult


def _executed_steps(result: RunResult) -> list[dict[str, Any]]:
    """Read ``result.executed_steps``, raising if the run didn't record any."""
    if result.executed_steps is None:
        raise ValueError("RunResult.executed_steps is required for this metric")
    return result.executed_steps


def task_success(case: EvalCase, result: RunResult) -> dict[str, Any]:
    """Heuristic pass/fail: did the run complete with zero ``"degraded"`` steps?"""
    steps = _executed_steps(result)
    degraded = [i for i, s in enumerate(steps) if s.get("status") == "degraded"]
    return {
        "success": not degraded,
        "n_steps": len(steps),
        "n_degraded_steps": len(degraded),
        "degraded_step_indices": degraded,
    }


def steps_to_completion(case: EvalCase, result: RunResult) -> dict[str, Any]:
    """Number of steps the run actually executed."""
    return {"steps_to_completion": len(_executed_steps(result))}


def plan_execution_alignment(case: EvalCase, result: RunResult) -> dict[str, Any]:
    """Do the run's executed steps match ``case.expected_steps`` 1:1, in order?

    Catches planner tool-choice mistakes (e.g. a lookup routed to a calculator) - not just
    whether execution obeyed its own authorized plan, which the coordinator always guarantees.
    """
    if case.expected_steps is None:
        raise ValueError("EvalCase.expected_steps is required for plan_execution_alignment")
    expected, executed = case.expected_steps, _executed_steps(result)
    mismatches: list[dict[str, Any]] = []
    for i in range(max(len(expected), len(executed))):
        exp = expected[i] if i < len(expected) else None
        act = executed[i] if i < len(executed) else None
        aligned = (
            exp is not None
            and act is not None
            and exp.executor_id == act.get("executor_id")
            and exp.tool_name == act.get("tool")
        )
        if not aligned:
            mismatches.append(
                {
                    "index": i,
                    "expected": (
                        {"executor_id": exp.executor_id, "tool_name": exp.tool_name}
                        if exp is not None
                        else None
                    ),
                    "actual": (
                        {"executor_id": act.get("executor_id"), "tool": act.get("tool")}
                        if act is not None
                        else None
                    ),
                },
            )
    return {
        "aligned": not mismatches,
        "n_expected_steps": len(expected),
        "n_executed_steps": len(executed),
        "mismatches": mismatches,
    }


def latency(case: EvalCase, result: RunResult) -> dict[str, Any]:
    """Wall-clock latency for the run, in milliseconds (``None`` if not recorded)."""
    return {"latency_ms": result.metadata.get("latency_ms")}


def token_counts(case: EvalCase, result: RunResult) -> dict[str, Any]:
    """Input/output/total token counts for the run (``None`` fields if not recorded)."""
    tokens_in = result.metadata.get("tokens_in")
    tokens_out = result.metadata.get("tokens_out")
    tokens_total = None if tokens_in is None or tokens_out is None else tokens_in + tokens_out
    return {"tokens_in": tokens_in, "tokens_out": tokens_out, "tokens_total": tokens_total}


def plan_adequacy(case: EvalCase, result: RunResult) -> dict[str, Any]:
    """Stub: LLM judge not yet wired; always returns a placeholder score."""
    return {"score": None, "rationale": None, "stub": True}
