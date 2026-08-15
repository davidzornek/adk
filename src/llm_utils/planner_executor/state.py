"""Graph state schemas for the planner-executor patterns (plan-then-act and interleaved).

Field names follow the logical schema in ``docs/4_planner_executor_agent_components.md``
(``plan_artifact``, ``authorized_steps``/``authorized_plan``, ``executed_steps``,
``observations``). Fields that accumulate one entry per node/executor invocation are
``Annotated[list[...], operator.add]`` so LangGraph concatenates the single-item-list
partial updates that ``graph.py``'s nodes and ``executor.py``'s ``DegradedModeExecutor``
return, instead of overwriting the accumulated history on each step.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class PlanThenActStep(BaseModel):
    """One step of a plan-then-act plan: which executor runs which tool, with what args.

    ``depends_on`` references prior steps by their (zero-based) index in the owning
    artifact's ``steps`` list.
    """

    executor_id: str
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[int] | None = None


class PlanThenActArtifact(BaseModel):
    """A structured, ordered plan produced by the planner before any tool runs."""

    steps: list[PlanThenActStep] = Field(default_factory=list)


class PlanThenActPlannerExecutorState(TypedDict, total=False):
    """Graph state for the plan-then-act topology (``graph.py``'s ``build_plan_then_act_graph``)."""

    task: str
    context: dict[str, Any]
    plan_artifact: PlanThenActArtifact | None
    authorized_plan: PlanThenActArtifact | None
    authorized_steps: list[PlanThenActStep]
    executed_steps: Annotated[list[dict[str, Any]], operator.add]
    observations: Annotated[list[str], operator.add]


def authorize_plan_from_artifact(
    state: PlanThenActPlannerExecutorState,
    *,
    validated: PlanThenActArtifact | None = None,
) -> dict[str, Any]:
    """Promote a plan artifact into ``authorized_plan`` / ``authorized_steps``.

    Args:
        state: Graph state (or a merged state dict); supplies ``plan_artifact`` when
            ``validated`` is not given.
        validated: Explicit artifact to authorize, e.g. a validator/gate node's edited
            plan. Takes precedence over ``state["plan_artifact"]`` when given.

    Returns:
        Dict with ``authorized_plan`` (the artifact, or ``None``) and ``authorized_steps``
        (its steps, or ``[]``).
    """
    artifact = validated if validated is not None else state.get("plan_artifact")
    steps = list(artifact.steps) if artifact is not None else []
    return {"authorized_plan": artifact, "authorized_steps": steps}


class InterleavedPlannerExecutorState(TypedDict, total=False):
    """Graph state for the interleaved topology (``graph.py``'s ``build_planner_executor_graph``).

    Minimal but correct: the interleaved topology is not demoed in this batch of work, but
    ``graph.py`` imports this symbol unconditionally, so it must exist and match how that
    module's nodes read and write it.
    """

    task: str
    context: dict[str, Any]
    plan_action: str
    next_tool_name: str | None
    next_tool_args: dict[str, Any]
    plan_rationale: str
    iteration: int
    planner_trace: Annotated[list[str], operator.add]
    observations: Annotated[list[str], operator.add]
    executed_steps: Annotated[list[dict[str, Any]], operator.add]
    max_iterations: int
    draft_output: dict[str, Any] | None
    stopped_reason: str
