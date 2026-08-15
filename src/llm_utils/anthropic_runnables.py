"""Anthropic-backed Runnable adapter for the plan-then-act planner.

Calls the Anthropic Messages API directly via ``client.messages.create`` (no LangChain
chat-model wrapper), forcing tool-use so the model's response always parses cleanly into a
:class:`~llm_utils.planner_executor.state.PlanThenActArtifact`. Planner-only: the drafter role
takes its system prompt through the invocation payload itself (see ``draft_state_update`` in
``planner_executor/nodes.py``) rather than at construction, so it isn't served by this adapter.
"""

from __future__ import annotations

import json
from typing import Any, cast

from anthropic import Anthropic
from anthropic.types import ToolChoiceToolParam, ToolParam
from langchain_core.runnables import Runnable
from langchain_core.runnables.config import RunnableConfig
from typing_extensions import override

from .planner_executor.state import PlanThenActArtifact

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


def _find_tool_use(response: Any, tool_name: str) -> Any:
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
            return block
    raise ValueError(f"Anthropic response did not include a {tool_name!r} tool_use block")


class AnthropicRunnable(Runnable[dict[str, Any], dict[str, Any]]):
    """Plan-then-act planner Runnable backed by the Anthropic Messages API.

    ``invoke`` sends ``input`` (the graph state, e.g. ``task``/``context``) as the user message
    alongside a static ``system`` prompt, forcing the model to call the ``submit_plan`` tool so
    its response schema always matches ``PlanThenActArtifact``. Returns
    ``{"plan_artifact": PlanThenActArtifact}`` — the shape ``produce_plan_node`` (in
    ``planner_executor/graph.py``) expects from a planner Runnable.

    Attributes:
        client: Anthropic client, e.g. from ``anthropic_client.get_anthropic_client()``.
        model: Anthropic model id to call.
        system_prompt: Static planner system prompt.
        max_tokens: Max tokens for the ``messages.create`` call.
    """

    def __init__(
        self,
        client: Anthropic,
        *,
        model: str,
        system_prompt: str,
        max_tokens: int = 2048,
    ) -> None:
        super().__init__()
        self._client = client
        self._model = model
        self._system_prompt = system_prompt
        self._max_tokens = max_tokens

    @override
    def invoke(
        self,
        input: dict[str, Any],
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=self._system_prompt,
            messages=[{"role": "user", "content": json.dumps(input, default=str)}],
            tools=[_SUBMIT_PLAN_TOOL],
            tool_choice=_SUBMIT_PLAN_TOOL_CHOICE,
        )
        tool_use = _find_tool_use(response, _SUBMIT_PLAN_TOOL_NAME)
        return {"plan_artifact": PlanThenActArtifact.model_validate(tool_use.input)}
