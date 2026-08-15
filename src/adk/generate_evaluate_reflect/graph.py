"""Generate-evaluate-reflect LangGraph builder (closed-loop retry)."""

from __future__ import annotations

import logging
from typing import Any, Literal

from langchain_core.runnables import Runnable
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph import END, StateGraph

from .state import GenerateEvaluateReflectState

logger = logging.getLogger(__name__)


def logical_graph_node_ids(compiled: Any) -> tuple[str, ...]:
    """Return logical LangGraph node ids in graph registration order (excludes ``__*`` nodes)."""
    return tuple(
        str(name)
        for name in compiled.get_graph().nodes
        if not str(name).startswith("__")
    )


def _route_after_evaluate(state: GenerateEvaluateReflectState) -> Literal["reflect", "sink"]:
    """After evaluate: sink on pass or exhausted budget, otherwise loop back through reflect.

    Args:
        state: Current graph state; reads ``eval_verdict``, ``attempt_index``, ``max_attempts``.

    Returns:
        ``sink`` when the candidate passed or the attempt budget is exhausted, else ``reflect``.
    """
    if state.get("eval_verdict") == "pass":
        return "sink"
    attempt_index = int(state.get("attempt_index") or 0)
    max_attempts = int(state.get("max_attempts") or 3)
    if attempt_index >= max_attempts:
        return "sink"
    return "reflect"


def build_ger_closed_loop_graph(
    *,
    generator: Runnable[dict[str, Any], dict[str, Any]],
    evaluator: Runnable[dict[str, Any], dict[str, Any]],
    reflector: Runnable[dict[str, Any], dict[str, Any]],
) -> Any:
    """Compile closed-loop retry: generate -> evaluate -> (conditional) -> reflect -> generate...
    -> sink -> END.

    ``generator`` must return ``{"candidate": ...}``. ``evaluator`` must return
    ``{"eval_verdict": "pass" | "fail", "eval_rationale": ...}``. ``reflector`` must return
    ``{"reflection_feedback": ...}``, consumed by the next ``generator`` invocation. The loop
    stops once ``evaluator`` reports ``"pass"`` or ``attempt_index`` reaches ``max_attempts``
    (default 3, read from state so callers can override per invocation).

    Returns:
        Compiled LangGraph ready for ``invoke`` / ``stream``.
    """

    def generate_node(
        state: GenerateEvaluateReflectState,
        config: RunnableConfig,
    ) -> dict[str, Any]:
        attempt_index = int(state.get("attempt_index") or 0) + 1
        logger.info("=== GENERATE NODE START (attempt %s) ===", attempt_index)
        out = dict(generator.invoke(dict(state), config))
        candidate = out.get("candidate")
        logger.info("=== GENERATE NODE COMPLETE ===")
        return {
            "candidate": candidate,
            "attempt_index": attempt_index,
            "attempts": [{"attempt_index": attempt_index, "candidate": candidate}],
        }

    def evaluate_node(
        state: GenerateEvaluateReflectState,
        config: RunnableConfig,
    ) -> dict[str, Any]:
        logger.info("=== EVALUATE NODE START ===")
        out = dict(evaluator.invoke(dict(state), config))
        logger.info("Eval verdict: %s", out.get("eval_verdict"))
        logger.info("=== EVALUATE NODE COMPLETE ===")
        return out

    def reflect_node(
        state: GenerateEvaluateReflectState,
        config: RunnableConfig,
    ) -> dict[str, Any]:
        logger.info("=== REFLECT NODE START ===")
        out = dict(reflector.invoke(dict(state), config))
        logger.info("=== REFLECT NODE COMPLETE ===")
        return out

    def sink_node(state: GenerateEvaluateReflectState) -> dict[str, Any]:
        passed = state.get("eval_verdict") == "pass"
        logger.info("=== SINK NODE (passed=%s) ===", passed)
        return {
            "accepted_artifact": state.get("candidate") if passed else None,
            "stop_reason": "all_pass" if passed else "budget_exhausted",
        }

    graph = StateGraph(GenerateEvaluateReflectState)
    graph.add_node("generate", generate_node)
    graph.add_node("evaluate", evaluate_node)
    graph.add_node("reflect", reflect_node)
    graph.add_node("sink", sink_node)

    graph.set_entry_point("generate")
    graph.add_edge("generate", "evaluate")
    graph.add_conditional_edges(
        "evaluate",
        _route_after_evaluate,
        {"reflect": "reflect", "sink": "sink"},
    )
    graph.add_edge("reflect", "generate")
    graph.add_edge("sink", END)

    return graph.compile()
