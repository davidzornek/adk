"""Anthropic-backed planner for the plan-then-act topology.

Configures the general-purpose :class:`~llm_utils.anthropic_runnables.AnthropicRunnable` with
a forced ``submit_plan`` tool call - schema derived from :class:`PlanThenActArtifact` itself -
so its response always parses cleanly into ``{"plan_artifact": PlanThenActArtifact}``, the
shape ``produce_plan_node`` (in ``graph.py``) expects from a planner Runnable.
"""

from __future__ import annotations

from typing import Any, cast

from anthropic import Anthropic
from anthropic.types import ToolChoiceToolParam, ToolParam
from langchain_core.runnables import Runnable

from ..anthropic_runnables import AnthropicRunnable
from .state import PlanThenActArtifact

_SUBMIT_PLAN_TOOL_NAME = "submit_plan"

# PlanThenActArtifact.model_json_schema() is a plain JSON Schema dict; Anthropic's ToolParam
# TypedDict expects a narrower shape, so it's cast rather than fought structurally.
_SUBMIT_PLAN_TOOL = cast(
    ToolParam,
    {
        "name": _SUBMIT_PLAN_TOOL_NAME,
        "description": "Submit the ordered plan of executor steps to run.",
        "input_schema": PlanThenActArtifact.model_json_schema(),
    },
)
_SUBMIT_PLAN_TOOL_CHOICE = cast(
    ToolChoiceToolParam,
    {"type": "tool", "name": _SUBMIT_PLAN_TOOL_NAME},
)


def _parse_plan_artifact(response: Any) -> dict[str, Any]:
    for block in response.content:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == _SUBMIT_PLAN_TOOL_NAME
        ):
            return {"plan_artifact": PlanThenActArtifact.model_validate(block.input)}
    raise ValueError(
        f"Anthropic response did not include a {_SUBMIT_PLAN_TOOL_NAME!r} tool_use block",
    )


def build_plan_then_act_planner(
    client: Anthropic,
    *,
    model: str,
    system_prompt: str,
    max_tokens: int = 2048,
) -> Runnable[dict[str, Any], dict[str, Any]]:
    """Build a plan-then-act planner Runnable backed by the Anthropic Messages API.

    Args:
        client: Anthropic client, e.g. from ``anthropic_client.get_anthropic_client()``.
        model: Anthropic model id to call.
        system_prompt: Static planner system prompt.
        max_tokens: Max tokens for the underlying ``messages.create`` call.

    Returns:
        A Runnable whose ``.invoke(dict(state), config)`` returns
        ``{"plan_artifact": PlanThenActArtifact}``, suitable as ``build_plan_then_act_graph``'s
        ``planner`` argument.
    """
    return AnthropicRunnable(
        client,
        model=model,
        system_prompt=system_prompt,
        tools=[_SUBMIT_PLAN_TOOL],
        tool_choice=_SUBMIT_PLAN_TOOL_CHOICE,
        max_tokens=max_tokens,
        response_parser=_parse_plan_artifact,
    )
