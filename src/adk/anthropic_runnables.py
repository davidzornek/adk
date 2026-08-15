"""General-purpose Runnable adapter over the Anthropic Messages API.

Any node that needs an LLM call - a planner, a drafter, an LLM-backed executor - can use an
``AnthropicRunnable`` instance, each configured for its own role via ``system_prompt``,
optional ``tools``/``tool_choice`` for forced structured output, and an optional
``response_parser`` that shapes the raw ``anthropic.types.Message`` into whatever dict its
node's state contract expects. Pattern-specific glue (e.g. the plan-then-act planner's
``output_plan`` tool schema and parsing into a ``PlanThenActArtifact``) lives alongside that
pattern's other code, not here - this module only knows how to call the API.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from anthropic import Anthropic
from anthropic.types import ToolChoiceParam, ToolParam
from langchain_core.runnables import Runnable
from langchain_core.runnables.config import RunnableConfig
from typing_extensions import override

# Given the raw ``anthropic.types.Message`` response, produce the dict `invoke` returns.
ResponseParser = Callable[[Any], dict[str, Any]]


def _default_response_parser(response: Any) -> dict[str, Any]:
    """Normalize a response into ``{"text": ..., "tool_calls": [{"name", "input"}, ...]}``."""
    text = "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )
    tool_calls = [
        {"name": block.name, "input": block.input}
        for block in response.content
        if getattr(block, "type", None) == "tool_use"
    ]
    return {"text": text, "tool_calls": tool_calls}


class AnthropicRunnable(Runnable[dict[str, Any], dict[str, Any]]):
    """Runnable that calls ``client.messages.create`` with a fixed model/system/tool config.

    ``invoke`` serializes ``input`` as the single user message, calls the API, and hands the
    response to ``response_parser`` (defaulting to a plain text/tool_calls dict).

    Attributes:
        client: Anthropic client, e.g. from ``anthropic_client.get_anthropic_client()``.
        model: Anthropic model id to call.
        system_prompt: Static system prompt for this role.
        tools: Tool definitions to offer the model, or ``None`` for no tools.
        tool_choice: Tool-choice directive (e.g. forced tool-use), or ``None`` to let the SDK
            default (only meaningful when ``tools`` is set).
        max_tokens: Max tokens for the ``messages.create`` call.
        response_parser: Shapes the raw response into the dict ``invoke`` returns.
    """

    def __init__(
        self,
        client: Anthropic,
        *,
        model: str,
        system_prompt: str,
        tools: list[ToolParam] | None = None,
        tool_choice: ToolChoiceParam | None = None,
        max_tokens: int = 2048,
        response_parser: ResponseParser = _default_response_parser,
    ) -> None:
        super().__init__()
        self._client = client
        self._model = model
        self._system_prompt = system_prompt
        self._tools = tools
        self._tool_choice = tool_choice
        self._max_tokens = max_tokens
        self._response_parser = response_parser

    @override
    def invoke(
        self,
        input: dict[str, Any],
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        create_kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": self._system_prompt,
            "messages": [{"role": "user", "content": json.dumps(input, default=str)}],
        }
        if self._tools is not None:
            create_kwargs["tools"] = self._tools
        if self._tool_choice is not None:
            create_kwargs["tool_choice"] = self._tool_choice
        response = self._client.messages.create(**create_kwargs)
        parsed = self._response_parser(response)
        parsed["usage"] = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }
        return parsed
