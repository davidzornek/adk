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
examples/               # Notebooks walking through the demos in src/adk/demos/
tests/
```

See [docs/1_intro_and_contents.md](docs/1_intro_and_contents.md) for the full
map of patterns and how they compose.

## Demo

[examples/plan_then_act_demo.ipynb](examples/plan_then_act_demo.ipynb) walks through
`adk.demos.plan_then_act_demo.DemoPlanThenActAgent`, a plan-then-act agent wired to a live
Tavily web-search tool and a sandboxed calculator tool. It can also be run headlessly:

```bash
uv run python -m adk.demos.plan_then_act_demo "<task>"
```

## Setup

The plan-then-act demo calls Anthropic directly and uses Tavily for real web search.
Create keys and export them:

- Anthropic: create a key at [console.anthropic.com](https://console.anthropic.com/), then
  `export ANTHROPIC_API_KEY=sk-ant-...`
- Tavily: create a key at [tavily.com](https://tavily.com/), then
  `export TAVILY_API_KEY=tvly-...`

`.env`/`.envrc` are already gitignored, so no extra tooling is required to keep keys out of
version control.

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
