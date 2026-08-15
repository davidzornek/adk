"""A fault-tolerant executor Runnable behind a degraded-mode boundary.

Each executor owns one or more capability tools and runs the one a plan step names
(``next_tool_name``). Unlike the fail-fast ``InterleavedExecutor`` (in
:mod:`~llm_utils.planner_executor.nodes`), a :class:`DegradedModeExecutor` catches
any tool exception and resolves it to a structured *degraded* step carrying the executor's
``degraded_mode`` message - so one failing tool degrades its own step instead of failing
the whole turn.

It satisfies the executor contract of
:class:`~llm_utils.planner_executor.nodes.PlanThenActExecutionCoordinator`
(consume ``next_tool_name`` / ``next_tool_args`` / ``context``; return ``observations``
and ``executed_steps``), so it drops into a coordinator's executor map keyed by
``executor_id``. Tools are plain callables ``(args, ctx) -> payload``, injected by the
caller - the boundary is intentionally agnostic to how a tool is implemented (in-process
today, a remote sub-agent call tomorrow).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, Callable

from langchain_core.runnables import Runnable
from langchain_core.runnables.config import RunnableConfig
from typing_extensions import override


log = logging.getLogger(__name__)

# A capability tool: called with ``(tool_args, context)`` and returning a payload.
ToolCallable = Callable[[dict[str, Any], dict[str, Any]], Any]


class DegradedModeExecutor(Runnable[dict[str, Any], dict[str, Any]]):
    """One executor behind a degraded-mode boundary; dispatches on ``next_tool_name``.

    Invocation contract - ``invoke`` reads from its ``input`` dict:

    - ``next_tool_name`` (str): the tool to run. Must be one of this executor's
      ``capability_tools`` or a :class:`ValueError` is raised (a coordinator routed a step
      to the wrong executor).
    - ``next_tool_args`` (dict): arguments forwarded to the tool callable.
    - ``context`` (dict): read-only context forwarded to the tool callable.

    and always returns a dict with two channels the coordinator appends:

    - ``observations`` (list[str]): one trace-readable line for the step.
    - ``executed_steps`` (list[dict]): one record ``{executor_id, tool, status, ...}`` where
      ``status`` is ``"ok"`` (with the tool ``payload``) or ``"degraded"`` (with an ``error``).

    Attributes:
        executor_id: Stable id for this executor; labels its observations/steps.
        capability_tools: The tool names this executor is permitted to run.
    """

    def __init__(
        self,
        *,
        executor_id: str,
        tools: Mapping[str, ToolCallable],
        degraded_mode: str,
    ) -> None:
        super().__init__()
        if not tools:
            raise ValueError(f"executor {executor_id!r} must own at least one tool")
        self.executor_id = executor_id
        self._tools = dict(tools)
        self.capability_tools = tuple(self._tools)
        self._degraded_mode = degraded_mode

    @override
    def invoke(
        self,
        input: dict[str, Any],
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        name = input.get("next_tool_name") or ""
        args = input.get("next_tool_args") or {}
        ctx = input.get("context") or {}
        tool_fn = self._tools.get(name)
        if tool_fn is None:
            raise ValueError(
                f"executor {self.executor_id!r} cannot run tool {name!r} "
                f"(owns {list(self.capability_tools)})",
            )
        try:
            payload = tool_fn(args, ctx)
        except Exception as exc:  # noqa: BLE001 - degraded boundary is intentionally broad
            log.warning("executor %s degraded: %s", self.executor_id, exc)
            observation = f"[{self.executor_id}] degraded: {self._degraded_mode}"
            step = {
                "executor_id": self.executor_id,
                "tool": name,
                "status": "degraded",
                "error": f"{type(exc).__name__}: {exc}",
            }
            return {"observations": [observation], "executed_steps": [step]}

        observation = f"[{self.executor_id}] {json.dumps(payload, default=str)}"
        step = {
            "executor_id": self.executor_id,
            "tool": name,
            "status": "ok",
            "payload": payload,
        }
        return {"observations": [observation], "executed_steps": [step]}
