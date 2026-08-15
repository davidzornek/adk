"""Graph state schema for the generate-evaluate-reflect closed-loop retry pattern.

Field names follow the logical schema in ``docs/4_generate_evaluate_reflect_agent_components.md``
(``candidate``, ``eval_verdict``/``eval_rationale``, ``reflection_feedback``,
``attempt_index``/``budget_remaining``, ``stop_reason``, ``accepted_artifacts``). ``attempts``
accumulates one entry per generate/evaluate cycle, so it is
``Annotated[list[dict[str, Any]], operator.add]`` and LangGraph concatenates the single-item-list
partial updates ``graph.py``'s ``generate_node`` returns, instead of overwriting the accumulated
history on each attempt.

Candidate artifacts are carried as a plain ``dict[str, Any]`` rather than a fixed pydantic model:
unlike a plan-then-act plan, GER candidates vary too widely by product (text, structured records,
tool args) for one shared schema to fit every subclass.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any

from typing_extensions import TypedDict


class GenerateEvaluateReflectState(TypedDict, total=False):
    """Graph state for the closed-loop retry topology (``graph.py``'s
    ``build_ger_closed_loop_graph``).
    """

    task: str
    context: dict[str, Any]
    candidate: dict[str, Any] | None
    eval_verdict: str | None
    eval_rationale: str | None
    reflection_feedback: str | None
    attempt_index: int
    max_attempts: int
    accepted_artifact: dict[str, Any] | None
    stop_reason: str | None
    attempts: Annotated[list[dict[str, Any]], operator.add]
