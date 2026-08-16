# adk

Agent development kit: reusable LangGraph/LangChain patterns for building and
evaluating LLM agents, plus an evaluation harness for scoring them against
LangSmith datasets.

## Layout

```
src/adk/
├── planner_executor/          # LangGraph-backed planner-executor agent base classes
├── generate_evaluate_reflect/ # LangGraph-backed generate-evaluate-reflect agent base classes
├── eval_harness/              # LangSmith-backed evaluation harness (scoring, rollups)
└── demos/                     # Runnable demo agents built on the framework above
docs/                          # Design docs: pattern cheatsheets, evaluation, composability guide
└── demos/                     # Notebooks walking through the demos in src/adk/demos/, run and
                                # committed with their output cells so they're readable on GitHub
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

[docs/demos/plan_then_act_demo.ipynb](docs/demos/plan_then_act_demo.ipynb) walks through
`adk.demos.plan_then_act_demo.DemoPlanThenActAgent`, a plan-then-act agent wired to a live
Tavily web-search tool and a sandboxed calculator tool. The demo task is intentionally
simple — the point is to prove the pattern's plumbing (real tool calls, executor routing,
dependency-wave scheduling, degraded-mode handling) end to end against live APIs, not to
showcase planning sophistication. Later examples will lean into tasks that actually exercise
reasoning quality.

[docs/demos/eval_plan_then_act_demo.ipynb](docs/demos/eval_plan_then_act_demo.ipynb) scores
that same agent with `adk.eval_harness.local_harness` — `run_and_score()` and `rollup()` — a
small, pure-local eval harness (no LangSmith) that runs a list of `EvalCase`s through the
agent, scores each with metric functions from `eval_harness.metrics`, and rolls the results up
into pass rate, average steps to completion, and alignment rate. It also scores a second,
larger set of eval cases synthesized by
[docs/demos/generate_eval_cases_demo.ipynb](docs/demos/generate_eval_cases_demo.ipynb), which
drives `adk.demos.generate_eval_cases_demo.EvalCaseGenerator` — a
`GenerateEvaluateReflectBase` (`adk.generate_evaluate_reflect`) subclass — to generate and
self-critique new cases in the hand-written set's three tool-routing categories, writing
accepted ones to
[docs/demos/data/generated_eval_cases.json](docs/demos/data/generated_eval_cases.json).

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
loop topology — and `eval_harness.harness` — a separate, LangSmith-`Client`-backed eval harness
— are both present in `src/adk/` as importable scaffolding for future work, but neither is wired
into the demo or the quickstart above.
