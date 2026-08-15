"""Planner-executor LangGraph builders (interleaved loop and plan-then-act)."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, Literal

from langchain_core.runnables import Runnable
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph import END, StateGraph

from .config import PlannerExecutorConfig
from .nodes import PlanThenActExecutionCoordinator, draft_state_update
from .state import (
    InterleavedPlannerExecutorState,
    PlanThenActArtifact,
    PlanThenActPlannerExecutorState,
    authorize_plan_from_artifact,
)

logger = logging.getLogger(__name__)


def logical_graph_node_ids(compiled: Any) -> tuple[str, ...]:
    """Return logical LangGraph node ids in graph registration order (excludes ``__*`` nodes)."""
    return tuple(
        str(name)
        for name in compiled.get_graph().nodes
        if not str(name).startswith("__")
    )


def _route_after_plan(state: InterleavedPlannerExecutorState) -> Literal["draft", "execute", "end"]:
    """After the planner speaks: either hand off to draft, run a tool next, or exit gracefully.

    Args:
        state: Current graph state; reads ``plan_action`` (``draft`` / ``stop`` / tool path).

    Returns:
        Next node name: ``draft``, ``execute``, or ``end`` (stop).
    """
    action = (state.get("plan_action") or "").lower()
    if action == "draft":
        return "draft"
    if action == "stop":
        return "end"
    return "execute"


def _route_after_execute(state: InterleavedPlannerExecutorState) -> Literal["plan", "draft"]:
    """After a tool runs: keep planning unless we have hit the iteration safety cap, then force draft.

    Args:
        state: Current graph state; reads ``executed_steps`` length and ``max_iterations``.

    Returns:
        ``plan`` to loop again, or ``draft`` when the cap is reached.
    """
    executed = state.get("executed_steps") or []
    cap = int(state.get("max_iterations") or 12)
    if len(executed) >= cap:
        return "draft"
    return "plan"


def draft_planner_executor(
    state: InterleavedPlannerExecutorState,
    llm: Any,
    *,
    drafter_system: str,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Turn accumulated tool observations plus context into the final structured draft.

    Args:
        state: Graph state providing ``task``, ``observations``, and ``context``.
        llm: Chat model used to produce the structured draft output JSON.
        drafter_system: Static system prompt (typically from LangSmith Hub).
        config: Optional LangChain runnable config for trace nesting under the graph run.

    Returns:
        Dict with ``draft_output`` (the structured draft produced by the drafter LLM).
    """
    return draft_state_update(
        dict(state),
        llm,
        drafter_system=drafter_system,
        config=config,
    )


def build_planner_executor_graph(
    *,
    planner: Runnable[dict[str, Any], Any],
    executor: Runnable[dict[str, Any], dict[str, Any]],
    draft_llm: Any,
    drafter_system: str,
    draft_model: str = "llama3-3-70b",
    draft_temperature: float = 0.4,
) -> StateGraph:
    """Assemble and compile the graph: plan <-> execute loops until draft or stop.

    In product terms: this is the "orchestration diagram" - which step comes next given what the
    planner just decided and how many tool calls have already happened. Swapping ``planner`` or
    ``executor`` lets you experiment with different planning or execution policies without
    rewriting this file.

    Args:
        planner: Runnable that maps state dict -> next plan decision (tool name/args or handoff).
        executor: Runnable that runs one tool and returns partial state (observations, steps).
        draft_llm: Chat model for the final draft node.
        drafter_system: Static drafter system prompt (typically from LangSmith Hub).
        draft_model: Model label for logging only (does not override ``draft_llm``).
        draft_temperature: Temperature label for logging only.

    Returns:
        Compiled LangGraph ready for ``invoke`` / ``stream``.
    """

    def plan_node(state: InterleavedPlannerExecutorState, config: RunnableConfig) -> dict[str, Any]:
        logger.info("=== PLAN NODE START ===")
        decision = planner.invoke(dict(state), config)
        trace_line = (
            f"action={decision.action} | tool={decision.tool_name or '-'} | "
            f"args={json.dumps(decision.tool_args, default=str)} | "
            f"rationale={decision.rationale}"
        )
        logger.info("Planner decision: %s", trace_line)
        iteration = state.get("iteration", 0) + 1
        logger.info("=== PLAN NODE COMPLETE (iteration %s) ===", iteration)
        return {
            "plan_action": decision.action,
            "next_tool_name": decision.tool_name,
            "next_tool_args": decision.tool_args,
            "plan_rationale": decision.rationale,
            "iteration": iteration,
            "planner_trace": [trace_line],
        }

    def execute_node(state: InterleavedPlannerExecutorState, config: RunnableConfig) -> dict[str, Any]:
        name = state.get("next_tool_name") or ""
        args = state.get("next_tool_args") or {}
        logger.info("=== EXECUTE NODE START === tool=%r args=%s", name, json.dumps(args, default=str))
        out = executor.invoke(dict(state), config)
        obs = out.get("observations") or []
        tail = obs[-1]
        preview = tail[:500] + ("..." if len(tail) > 500 else "")
        logger.info("Tool observation preview: %s", preview)
        logger.info("=== EXECUTE NODE COMPLETE ===")
        return out

    def draft_node(state: InterleavedPlannerExecutorState, config: RunnableConfig) -> dict[str, Any]:
        mode = f"llm model={draft_model!r} temp={draft_temperature}"
        logger.info("=== DRAFT NODE START (%s) ===", mode)
        result = draft_planner_executor(
            dict(state),
            draft_llm,
            drafter_system=drafter_system,
            config=config,
        )
        preview = json.dumps(result.get("draft_output"), default=str)
        logger.info(
            "=== DRAFT NODE COMPLETE draft_output=%s ===",
            preview[:120] + ("..." if len(preview) > 120 else ""),
        )
        return result

    def stop_node(_state: InterleavedPlannerExecutorState) -> dict[str, Any]:
        logger.info("=== STOP NODE (planner requested end) ===")
        return {"stopped_reason": "planner_stop"}

    graph = StateGraph(InterleavedPlannerExecutorState)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("draft", draft_node)
    graph.add_node("stop", stop_node)

    graph.set_entry_point("plan")
    graph.add_conditional_edges(
        "plan",
        _route_after_plan,
        {"draft": "draft", "execute": "execute", "end": "stop"},
    )
    graph.add_conditional_edges(
        "execute",
        _route_after_execute,
        {"plan": "plan", "draft": "draft"},
    )
    graph.add_edge("draft", END)
    graph.add_edge("stop", END)

    return graph.compile()


def build_plan_then_act_graph(
    *,
    planner: Runnable[dict[str, Any], dict[str, Any]],
    executors: Mapping[str, Runnable[dict[str, Any], dict[str, Any]]],
    drafter: Runnable[dict[str, Any], dict[str, Any]],
    drafter_system: str,
    validator: Runnable[dict[str, Any], dict[str, Any]] | None = None,
    config: PlannerExecutorConfig | None = None,
) -> Any:
    """Compile plan-then-act: produce_plan -> [validate_plan] -> execute_plan -> draft_response
    -> END.

    ``executors`` maps executor id -> Runnable. Step routing uses ``executor_id`` on the step
    or ``config.tools_by_executor``. Parallel work runs in the coordinator at ``execute_plan``.
    ``drafter`` synthesizes ``execute_plan``'s observations into a final ``draft_output``; it does
    not re-author the plan artifact.
    """
    coordinator = PlanThenActExecutionCoordinator(executors, config=config)

    def produce_plan_node(
        state: PlanThenActPlannerExecutorState,
        config: RunnableConfig,
    ) -> dict[str, Any]:
        out = dict(planner.invoke(dict(state), config))
        if validator is not None:
            return out
        merged: PlanThenActPlannerExecutorState = {**state, **out}
        return {**out, **authorize_plan_from_artifact(merged)}

    def execute_plan_node(
        state: PlanThenActPlannerExecutorState,
        config: RunnableConfig,
    ) -> dict[str, Any]:
        return dict(coordinator.invoke(dict(state), config))

    def draft_response_node(
        state: PlanThenActPlannerExecutorState,
        config: RunnableConfig,
    ) -> dict[str, Any]:
        return draft_state_update(
            dict(state),
            drafter,
            drafter_system=drafter_system,
            config=config,
        )

    graph = StateGraph(PlanThenActPlannerExecutorState)
    graph.add_node("produce_plan", produce_plan_node)
    if validator is not None:

        def validate_plan_node(
            state: PlanThenActPlannerExecutorState,
            config: RunnableConfig,
        ) -> dict[str, Any]:
            out = dict(validator.invoke(dict(state), config))
            validated: PlanThenActArtifact | None = out.get("plan_artifact") or out.get(
                "authorized_plan"
            )
            return {**out, **authorize_plan_from_artifact(state, validated=validated)}

        graph.add_node("validate_plan", validate_plan_node)
    graph.add_node("execute_plan", execute_plan_node)
    graph.add_node("draft_response", draft_response_node)
    graph.set_entry_point("produce_plan")

    if validator is not None:
        graph.add_edge("produce_plan", "validate_plan")
        graph.add_edge("validate_plan", "execute_plan")
    else:
        graph.add_edge("produce_plan", "execute_plan")

    graph.add_edge("execute_plan", "draft_response")
    graph.add_edge("draft_response", END)
    return graph.compile()
