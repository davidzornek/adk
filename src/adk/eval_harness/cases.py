"""Generic eval-harness rows: ``EvalCase`` (dataset row) and ``RunResult`` (one completed run).

``RunResult``'s shape matches what ``planner_executor.base.PlannerExecutorBase.to_eval_run_result``
builds from ``invoke()`` output. ``metrics.py``'s functions match ``MetricFn`` below.

This is a new, separate, local-only harness; ``eval_harness.harness`` (the LangSmith-``Client``-
backed harness) is pre-existing scaffolding, permanently unreachable (see its own module
docstring and the ``ruff``/``mypy`` excludes in ``pyproject.toml``), and stays untouched.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ExpectedStep(BaseModel):
    """One reference step (executor + tool) an :class:`EvalCase` expects a run to take, in order."""

    executor_id: str
    tool_name: str


class EvalCase(BaseModel):
    """One dataset row: a task to run plus optional ground truth for scoring the result."""

    id: str
    task: str
    context: dict[str, Any] = Field(default_factory=dict)
    expected_output: str | dict[str, Any] | list[Any] | None = None
    expected_steps: list[ExpectedStep] | None = None


class RunResult(BaseModel):
    """One completed run of an :class:`EvalCase`."""

    case_id: str
    run_id: str | None = None
    output: str | dict[str, Any] | list[Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    executed_steps: list[dict[str, Any]] | None = None


# Custom scorers must look like this: two positional args, no *args/**kwargs. Structurally
# identical to eval_harness.harness.MetricFn; defined fresh here since harness.py is dead
# scaffolding (see its module docstring) and cannot be imported.
MetricFn = Callable[[EvalCase, RunResult], Mapping[str, Any] | BaseModel]


def dump_eval_cases(cases: Sequence[EvalCase], path: str | Path) -> None:
    """Write ``cases`` to ``path`` as a JSON array, creating parent directories as needed."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps([case.model_dump() for case in cases], indent=2) + "\n")


def load_eval_cases(path: str | Path) -> list[EvalCase]:
    """Load a list of :class:`EvalCase` rows from a JSON file written by :func:`dump_eval_cases`."""
    rows = json.loads(Path(path).read_text())
    return [EvalCase.model_validate(row) for row in rows]
