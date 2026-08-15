# adk

Agent development kit: reusable LangGraph/LangChain patterns for building and
evaluating LLM agents, plus an evaluation harness for scoring them against
LangSmith datasets.

## Layout

```
src/llm_utils/
├── planner_executor/   # LangGraph-backed planner-executor agent base classes
└── eval_harness/       # LangSmith-backed evaluation harness (scoring, rollups)
docs/                   # Design docs: pattern cheatsheets, evaluation, composability guide
tests/
```

See [docs/1_intro_and_contents.md](docs/1_intro_and_contents.md) for the full
map of patterns and how they compose.

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
