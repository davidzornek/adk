# adk

Agent development kit: reusable LangGraph/LangChain patterns for building and
evaluating LLM agents, plus a local evaluation harness for scoring them.

## Layout

```
src/adk/
├── planner_executor/          # LangGraph-backed planner-executor agent base classes
├── generate_evaluate_reflect/ # LangGraph-backed generate-evaluate-reflect agent base classes
├── eval_harness/              # Evaluation harness (scoring, rollups)
└── demos/                     # Runnable demo agents built on the framework above
docs/                          # Design docs: pattern cheatsheets, evaluation, composability guide
├── demos/                     # Notebooks walking through the demos in src/adk/demos/, run and
│                               # committed with their output cells so they're readable on GitHub
└── experiments/               # Notebooks answering a specific evaluation question via the demos
                                # above, e.g. an ablation — also run and committed with output
tests/
```

See [docs/1_intro_and_contents.md](docs/1_intro_and_contents.md) for the full
map of patterns and how they compose.

## Quickstart

```bash
uv sync
cp .env.example .env   # paste in ANTHROPIC_API_KEY + TAVILY_API_KEY — see Setup below
uv run python -m adk.demos.plan_then_act_demo "<task>"
```

That last command runs the plan-then-act demo agent end to end against live Anthropic +
Tavily calls and prints the authorized plan, executed steps, and final state. To score that
same agent against a small hand-written eval set, run the eval harness demo notebook:

```bash
uv run jupyter nbconvert --to notebook --execute --output-dir /tmp \
  docs/demos/eval_plan_then_act_demo.ipynb
```

or just open [docs/demos/eval_plan_then_act_demo.ipynb](docs/demos/eval_plan_then_act_demo.ipynb)
directly — it's committed with output cells from a real run, so it's readable on GitHub
without an API key.

## Demo

Built `DemoPlanThenActAgent` (`adk.demos.plan_then_act_demo`) — a plan-then-act agent wired to
a live Tavily web-search tool and a sandboxed calculator tool — to prove the pattern's plumbing
end to end against live APIs: real tool calls, executor routing, dependency-wave scheduling,
degraded-mode handling. The demo task is intentionally simple (population lookups + arithmetic)
so the plumbing stays legible; it's not meant to showcase planning sophistication. Walkthrough:
[docs/demos/plan_then_act_demo.ipynb](docs/demos/plan_then_act_demo.ipynb).

Scored that agent against a small hand-written eval set (3 cases spanning its three tool-routing
categories) with `adk.eval_harness.local_harness`, a pure-local harness built for
this: **100% pass rate, 100% plan-execution alignment**. To check that result wasn't just an
artifact of hand-picking easy cases, also built `EvalCaseGenerator`
(`adk.demos.generate_eval_cases_demo`) — a `GenerateEvaluateReflectBase` subclass that generates
and self-critiques new cases in the same three categories — and scored its 6 accepted cases the
same way: same **100%/100%**. Walkthroughs:
[docs/demos/eval_plan_then_act_demo.ipynb](docs/demos/eval_plan_then_act_demo.ipynb),
[docs/demos/generate_eval_cases_demo.ipynb](docs/demos/generate_eval_cases_demo.ipynb).

## Experiments

Tested whether that eval harness actually distinguishes *"the plan was right but a tool failed"*
from *"the plan was wrong"*, by disabling `web_search` (planner prompt, config, and the
`calculate` tool all left untouched) and rerunning the same three hand-written cases. Result:
**pass rate dropped from 100% to 33%** — exactly the two search-dependent cases degraded —
while **alignment rate held at 100%**, since the planner kept routing every step to the right
executor and tool even though the tool call itself failed; only `DegradedModeExecutor`'s fault
boundary saw the outage. That's the harness's `task_success` / `plan_execution_alignment` split
doing its job: a single pass/fail number can't tell those two failure modes apart, and this
result shows the two metrics together do. Notebook (run and committed with output):
[docs/experiments/web_search_ablation.ipynb](docs/experiments/web_search_ablation.ipynb).

## Setup

The plan-then-act demo calls Anthropic directly and uses Tavily for real web search.

- Anthropic: create a key at [console.anthropic.com](https://console.anthropic.com/)
- Tavily: create a key at [tavily.com](https://tavily.com/)

Copy `.env.example` to `.env` and paste both keys in — the demo notebook and CLI both call
`load_dotenv()` on startup, so `.env` is picked up automatically. `.env`/`.envrc` are already
gitignored, so no extra tooling is required to keep keys out of version control.

## Development

Dependencies are managed with [uv](https://docs.astral.sh/uv/).

```bash
uv sync

uv run ruff check .
uv run mypy src
uv run pytest
```

## Status

Only the plan-then-act topology is demoed above, now paired with a generate-evaluate-reflect
loop (`adk.generate_evaluate_reflect`) that synthesizes additional eval cases for it (see Demo
section). `planner_executor.graph.build_planner_executor_graph` — the interleaved plan/execute-
loop topology — and `eval_harness.harness` — a separate eval harness backed by an external
tracing/dataset service — are both present in `src/adk/` as importable scaffolding for future
work, but neither is wired into the demo or the quickstart above.
