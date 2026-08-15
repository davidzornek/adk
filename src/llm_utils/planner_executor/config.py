"""Shared planner-executor configuration: tool ownership and routing fallback."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlannerExecutorConfig(BaseModel):
    """Centralized planner-executor configuration: tool ownership and routing fallback."""

    tools_by_executor: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    def tools_for_node(self, node_id: str) -> tuple[str, ...]:
        """Tools owned by ``node_id`` (empty tuple if the node owns none)."""
        return self.tools_by_executor.get(node_id, ())
