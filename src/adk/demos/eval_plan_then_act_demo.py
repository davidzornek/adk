"""Local eval harness demo: score ``DemoPlanThenActAgent`` against a handful of eval cases.

Reuses ``DemoPlanThenActAgent`` (``adk.demos.plan_then_act_demo``) unchanged - this module only
adds ``EvalCase``s and wires them through ``eval_harness.local_harness.run_and_score`` /
``rollup``. Calls live Anthropic + Tavily APIs (same requirements as the underlying demo); this
is the manual smoke test for the local eval harness, not a unit test.

Usage::

    uv run python -m adk.demos.eval_plan_then_act_demo
"""

from __future__ import annotations

from dotenv import load_dotenv

from adk.eval_harness.cases import EvalCase, ExpectedStep
from adk.eval_harness.local_harness import rollup, run_and_score
from adk.eval_harness.metrics import (
    latency,
    plan_execution_alignment,
    steps_to_completion,
    task_success,
    token_counts,
)

from .plan_then_act_demo import DEFAULT_TASK, DemoPlanThenActAgent

CASES = [
    EvalCase(
        id="population_lookup",
        task="What is the current population of France?",
        expected_steps=[ExpectedStep(executor_id="search", tool_name="web_search")],
    ),
    EvalCase(
        id="arithmetic",
        task="What is 482 times 17?",
        expected_steps=[ExpectedStep(executor_id="calc", tool_name="calculate")],
    ),
    EvalCase(
        id="combined_population",
        task=DEFAULT_TASK,
        expected_steps=[
            ExpectedStep(executor_id="search", tool_name="web_search"),
            ExpectedStep(executor_id="search", tool_name="web_search"),
            ExpectedStep(executor_id="calc", tool_name="calculate"),
        ],
    ),
]

METRICS = [task_success, steps_to_completion, plan_execution_alignment, latency, token_counts]


def main() -> None:
    load_dotenv()

    agent = DemoPlanThenActAgent()
    rows = run_and_score(CASES, agent, METRICS)

    header = f"{'case_id':<20} {'success':<8} {'steps':<6} {'aligned':<8} {'latency_ms':<11} tokens"
    print(header)
    for row in rows:
        tokens = f"{row.get('tokens_in')}in/{row.get('tokens_out')}out"
        print(
            f"{row['case_id']:<20} {str(row['success']):<8} {row['steps_to_completion']:<6} "
            f"{str(row['aligned']):<8} {row['latency_ms']:<11.1f} {tokens}",
        )

    print("\nRollup:")
    for key, value in rollup(rows).items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
