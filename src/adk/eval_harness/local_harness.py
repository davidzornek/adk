"""Local, pure-Python eval harness: run cases through an agent, score, roll up.

Every case is invoked in-process and scored inline - no ``langsmith.Client`` anywhere in this
file. Builds on :mod:`eval_harness.cases` (data model) and :mod:`eval_harness.metrics` (scorers);
:mod:`eval_harness.harness` (``SingleLLMEvalHarness``) is a separate, LangSmith-backed harness
this module does not touch.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import BaseModel

from adk.eval_harness.cases import EvalCase, MetricFn, RunResult


class EvalAgent(Protocol):
    """Runtime shape ``run_and_score`` needs: matches ``PlannerExecutorBase``'s public surface."""

    def invoke(self, input: dict[str, Any]) -> dict[str, Any]: ...

    def to_eval_run_result(
        self,
        out: dict[str, Any],
        *,
        case_id: str,
        output: str | dict[str, Any] | list[Any] | None = None,
    ) -> RunResult: ...


def run_and_score(
    cases: Sequence[EvalCase],
    agent: EvalAgent,
    metrics: Sequence[MetricFn],
) -> list[dict[str, Any]]:
    """Invoke ``agent`` on each case and score it, returning one flat dict per case.

    Each row merges ``case_id``, ``run_id``, and every metric's returned mapping - built-in
    metrics (see ``eval_harness.metrics``) use disjoint key sets by design, so a flat merge loses
    nothing.
    """
    rows: list[dict[str, Any]] = []
    for case in cases:
        out = agent.invoke({"task": case.task, "context": case.context})
        result = agent.to_eval_run_result(out, case_id=case.id, output=out.get("draft_output"))
        row: dict[str, Any] = {"case_id": result.case_id, "run_id": result.run_id}
        for metric in metrics:
            raw = metric(case, result)
            row.update(raw.model_dump() if isinstance(raw, BaseModel) else dict(raw))
        rows.append(row)
    return rows


def rollup(scored_rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate ``run_and_score`` rows: pass rate, avg steps to completion, alignment rate.

    Each aggregate is computed only over rows that carry the relevant metric's key, so a rollup
    over rows scored with a partial metric list silently omits the aggregates it can't compute.
    """
    out: dict[str, Any] = {"n_cases": len(scored_rows)}

    successes = [row["success"] for row in scored_rows if "success" in row]
    if successes:
        out["pass_rate"] = sum(successes) / len(successes)

    steps = [row["steps_to_completion"] for row in scored_rows if "steps_to_completion" in row]
    if steps:
        out["avg_steps_to_completion"] = sum(steps) / len(steps)

    aligned = [row["aligned"] for row in scored_rows if "aligned" in row]
    if aligned:
        out["alignment_rate"] = sum(aligned) / len(aligned)

    return out
