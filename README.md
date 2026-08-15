# adk

Agent development kit: reusable LangGraph/LangChain patterns for building and
evaluating LLM agents, plus an evaluation harness for scoring them against
LangSmith datasets.

## Layout

```
src/adk/
├── planner_executor/   # LangGraph-backed planner-executor agent base classes
├── eval_harness/       # LangSmith-backed evaluation harness (scoring, rollups)
└── demos/              # Runnable demo agents built on the framework above
docs/                   # Design docs: pattern cheatsheets, evaluation, composability guide
└── demos/              # Notebooks walking through the demos in src/adk/demos/, run and
                         # committed with their output cells so they're readable on GitHub
tests/
```

See [docs/1_intro_and_contents.md](docs/1_intro_and_contents.md) for the full
map of patterns and how they compose.

## Demo

[docs/demos/plan_then_act_demo.ipynb](docs/demos/plan_then_act_demo.ipynb) walks through
`adk.demos.plan_then_act_demo.DemoPlanThenActAgent`, a plan-then-act agent wired to a live
Tavily web-search tool and a sandboxed calculator tool. The demo task is intentionally
simple — the point is to prove the pattern's plumbing (real tool calls, executor routing,
dependency-wave scheduling, degraded-mode handling) end to end against live APIs, not to
showcase planning sophistication. Later examples will lean into tasks that actually exercise
reasoning quality. It can also be run headlessly:

```bash
uv run python -m adk.demos.plan_then_act_demo "<task>"
```

[docs/demos/eval_plan_then_act_demo.ipynb](docs/demos/eval_plan_then_act_demo.ipynb) scores
that same agent with `adk.eval_harness.local_harness` — `run_and_score()` and `rollup()` — a
small, pure-local eval harness (no LangSmith) that runs a list of `EvalCase`s through the
agent, scores each with metric functions from `eval_harness.metrics`, and rolls the results up
into pass rate, average steps to completion, and alignment rate.

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

Early scaffolding. `planner_executor` and `eval_harness` reference sibling
modules (`config`, `nodes`, `state`, `cases`, ...) that haven't landed yet.
