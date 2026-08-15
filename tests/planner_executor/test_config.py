from __future__ import annotations

from llm_utils.planner_executor.config import PlannerExecutorConfig


def test_tools_for_node_returns_mapped_tools() -> None:
    config = PlannerExecutorConfig(tools_by_executor={"search": ("web_search",)})

    assert config.tools_for_node("search") == ("web_search",)


def test_tools_for_node_returns_empty_tuple_for_unknown_node() -> None:
    config = PlannerExecutorConfig()

    assert config.tools_for_node("search") == ()


def test_default_construction_has_empty_tools_by_executor() -> None:
    assert PlannerExecutorConfig().tools_by_executor == {}
