"""Plan-then-act execution coordinator and draft-state helper for the planner-executor patterns."""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langchain_core.runnables import Runnable
from langchain_core.runnables.config import RunnableConfig

from .config import PlannerExecutorConfig
from .state import PlanThenActStep


class PlanThenActExecutionCoordinator:
    """Routes authorized plan steps to their executors and merges results.

    Steps are grouped into dependency waves via ``PlanThenActStep.depends_on`` (indices into the
    owning plan's ``steps`` list); each wave's steps run concurrently, and merged
    ``observations``/``executed_steps`` are ordered by original step index (not completion order)
    so the combined result stays deterministic.
    """

    def __init__(
        self,
        executors: Mapping[str, Runnable[dict[str, Any], dict[str, Any]]],
        config: PlannerExecutorConfig | None = None,
        max_workers: int | None = None,
    ) -> None:
        self._executors = dict(executors)
        self.config = config or PlannerExecutorConfig()
        self.max_workers = max_workers

    def invoke(
        self,
        state: dict[str, Any],
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        steps: list[PlanThenActStep] = state.get("authorized_steps") or []
        context = state.get("context") or {}
        # Resolve every step's executor before running any of them, so an unroutable step aborts
        # the whole plan with no partial tool calls.
        resolved = [self._resolve_executor(step) for step in steps]

        def run_step(i: int) -> tuple[int, dict[str, Any]]:
            step = steps[i]
            out = resolved[i].invoke(
                {
                    "next_tool_name": step.tool_name,
                    "next_tool_args": step.tool_args,
                    "context": context,
                },
                config,
            )
            return i, out

        results: dict[int, dict[str, Any]] = {}
        completed: set[int] = set()
        remaining = set(range(len(steps)))
        while remaining:
            wave = [
                i
                for i in remaining
                if all(dep in completed for dep in (steps[i].depends_on or []))
            ]
            if not wave:
                raise ValueError(
                    f"cannot schedule steps {sorted(remaining)}: cyclic or unresolved depends_on",
                )
            pool_size = min(len(wave), self.max_workers) if self.max_workers else len(wave)
            with ThreadPoolExecutor(max_workers=pool_size) as pool:
                for i, out in pool.map(run_step, wave):
                    results[i] = out
            completed.update(wave)
            remaining.difference_update(wave)

        observations: list[str] = []
        executed_steps: list[dict[str, Any]] = []
        for i in range(len(steps)):
            observations.extend(results[i].get("observations") or [])
            executed_steps.extend(results[i].get("executed_steps") or [])

        return {"observations": observations, "executed_steps": executed_steps}

    def _resolve_executor(
        self,
        step: PlanThenActStep,
    ) -> Runnable[dict[str, Any], dict[str, Any]]:
        executor = self._executors.get(step.executor_id)
        if executor is not None:
            return executor
        for executor_id, tool_names in self.config.tools_by_executor.items():
            if step.tool_name in tool_names:
                fallback = self._executors.get(executor_id)
                if fallback is not None:
                    return fallback
        raise ValueError(
            f"no executor found for step (executor_id={step.executor_id!r}, "
            f"tool_name={step.tool_name!r})",
        )


def draft_state_update(
    state: dict[str, Any],
    llm: Any,
    *,
    drafter_system: str,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Invoke ``llm`` as a ``Runnable[dict, dict]`` to turn observations into a structured draft."""
    payload = {
        "drafter_system": drafter_system,
        "task": state.get("task"),
        "context": state.get("context") or {},
        "observations": state.get("observations") or [],
    }
    draft_output = dict(llm.invoke(payload, config))
    usage = draft_output.pop("usage", None)
    return {"draft_output": draft_output, "token_usage": [usage] if usage is not None else []}
