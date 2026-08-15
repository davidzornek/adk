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
