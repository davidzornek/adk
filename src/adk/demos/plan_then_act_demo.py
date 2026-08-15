"""End-to-end plan-then-act demo: real web search + a safe calculator, two live tools.

Wires ``adk.planner_executor``'s plan-then-act building blocks (config, executors, graph,
base class) around two heterogeneous tools behind ``DegradedModeExecutor`` boundaries: Tavily
web search and a sandboxed arithmetic evaluator. Nothing here re-implements planner-executor
plumbing - it composes existing pieces from ``build_plan_then_act_planner``,
``AnthropicRunnable``, ``DegradedModeExecutor``, and ``build_plan_then_act_graph``.

See ``docs/demos/plan_then_act_demo.ipynb`` for a walkthrough that imports this module and
explains each piece as it's assembled and run.

Deliberately contrived, on purpose: the default task ("look up the current population of
France and Germany, then calculate their combined population") is not chosen to show off
planning sophistication - it's chosen because it's small and predictable enough to make the
*plumbing* legible: real tool calls crossing two heterogeneous executors, dependency-wave
scheduling, degraded-mode handling, and the plan-then-act topology itself, all running against
live APIs instead of fakes. It does not demonstrate anything worth calling reasoning ability.
Later examples, built on the same base classes, will lean into tasks that actually exercise
planning quality; this one's job is narrower - prove the wiring holds end to end.

Plan-then-act tradeoff worth calling out: ``build_plan_then_act_graph`` plans once, before any
tool runs, so a step's ``tool_args`` are fixed by the planner's own judgment - there is no
templating that feeds one step's tool output into a later step's arguments. The default task
still exercises real multi-step orchestration: the calculate step's ``depends_on`` forces both
search steps to complete first, and the planner has to route each step to the executor that
owns its tool. What it does *not* do is thread the live search numbers into the calculator's
expression - that data-flow-between-steps capability belongs to the interleaved pattern, not
plan-then-act. This is an intentional pattern tradeoff, not a bug.

Requires ``ANTHROPIC_API_KEY`` and ``TAVILY_API_KEY`` (see README's Setup section).

Usage::

    uv run python -m adk.demos.plan_then_act_demo
    uv run python -m adk.demos.plan_then_act_demo "<custom task>"
"""

from __future__ import annotations

import argparse
import ast
import operator
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

from ..anthropic_client import get_anthropic_client
from ..anthropic_runnables import AnthropicRunnable
from ..planner_executor.base import PlannerExecutorBase
from ..planner_executor.config import PlannerExecutorConfig
from ..planner_executor.executor import DegradedModeExecutor
from ..planner_executor.graph import build_plan_then_act_graph
from ..planner_executor.planner import build_plan_then_act_planner
from ..search_client import get_search_client

DEFAULT_MODEL = "claude-sonnet-5"

DEFAULT_TASK = (
    "Look up the current population of France and Germany, then calculate their "
    "combined population."
)

_SEARCH_MAX_RESULTS = 3

PLANNER_SYSTEM_PROMPT = """\
You are the planner for a plan-then-act agent with two executors, each owning one tool:

- executor_id="search", tool_name="web_search", tool_args={"query": <str>}
  Runs a live web search and returns the top result snippets.
- executor_id="calc", tool_name="calculate", tool_args={"expression": <str>}
  Evaluates a numeric arithmetic expression (+, -, *, /, //, %, **) and returns the result.
  The expression must be a literal arithmetic expression (numbers only, no variables or
  function calls) - fill in numbers from your own knowledge, since calculate steps run
  concurrently with (not after seeing the output of) search steps.

Given the user's task, output an ordered list of steps via the output_plan tool. Use
depends_on (zero-based indices into the steps list) to record which steps a step should be
scheduled after; independent steps run concurrently.
"""

DRAFTER_SYSTEM_PROMPT = """\
You are the drafter for a plan-then-act agent. Given the original task and the observations
gathered by its executors, write a concise, direct final answer to the task.
"""


def web_search(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Tool: run a live Tavily search and return top-N result snippets."""
    query = args["query"]
    client = get_search_client()
    response = client.search(query=query, max_results=_SEARCH_MAX_RESULTS)
    results = [
        {"title": r.get("title"), "url": r.get("url"), "snippet": r.get("content")}
        for r in (response.get("results") or [])[:_SEARCH_MAX_RESULTS]
    ]
    return {"query": query, "results": results}


_BIN_OPS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type[ast.unaryop], Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _eval_node(node: ast.expr) -> float:
    """Recursively evaluate an allow-listed arithmetic AST node (no names, no calls)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(
        node.value, bool
    ):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError(f"unsupported expression element: {ast.dump(node)}")


def _safe_eval(expression: str) -> float:
    """Evaluate a numeric arithmetic expression without ``eval()`` (input may be LLM-influenced)."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid expression: {expression!r}") from exc
    return _eval_node(tree.body)


def calculate(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Tool: safely evaluate a numeric arithmetic expression."""
    expression = args["expression"]
    return {"expression": expression, "result": _safe_eval(expression)}


def default_config() -> PlannerExecutorConfig:
    """Default tool-ownership config for :class:`DemoPlanThenActAgent`."""
    return PlannerExecutorConfig(
        tools_by_executor={
            "search": ("web_search",),
            "calc": ("calculate",),
        },
    )


class DemoPlanThenActAgent(PlannerExecutorBase):
    """Concrete plan-then-act agent: real Tavily search + a safe calculator tool."""

    def __init__(
        self,
        *,
        client: Anthropic | None = None,
        model: str = DEFAULT_MODEL,
        config: PlannerExecutorConfig | None = None,
    ) -> None:
        self._client = client or get_anthropic_client()
        self._model = model
        super().__init__(config=config or default_config())

    @property
    def variant(self) -> str:
        return "plan_then_act_demo"

    def _input_to_state(self, input: dict[str, Any]) -> dict[str, Any]:
        return {"task": input["task"], "context": input.get("context", {})}

    def _build_graph(self) -> Any:
        planner = build_plan_then_act_planner(
            self._client,
            model=self._model,
            system_prompt=PLANNER_SYSTEM_PROMPT,
        )
        drafter = AnthropicRunnable(
            self._client,
            model=self._model,
            system_prompt=DRAFTER_SYSTEM_PROMPT,
        )
        executors = {
            "search": DegradedModeExecutor(
                executor_id="search",
                tools={"web_search": web_search},
                degraded_mode="Web search is temporarily unavailable.",
            ),
            "calc": DegradedModeExecutor(
                executor_id="calc",
                tools={"calculate": calculate},
                degraded_mode="Calculation failed.",
            ),
        }
        return build_plan_then_act_graph(
            planner=planner,
            executors=executors,
            drafter=drafter,
            drafter_system=DRAFTER_SYSTEM_PROMPT,
            validator=None,
            config=self.config,
        )


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", nargs="?", default=DEFAULT_TASK, help="Task for the agent to run.")
    args = parser.parse_args()

    agent = DemoPlanThenActAgent()
    out = agent.invoke({"task": args.task, "context": {}})

    print(f"Task: {args.task}\n")

    print("Authorized plan:")
    for i, step in enumerate(out.get("authorized_steps") or []):
        print(
            f"  {i}. [{step.executor_id}] {step.tool_name}({step.tool_args}) "
            f"depends_on={step.depends_on}",
        )

    print("\nExecuted steps:")
    for step in out.get("executed_steps") or []:
        print(f"  - {step}")

    print("\nFinal draft output:")
    print(out.get("draft_output"))


if __name__ == "__main__":
    main()
