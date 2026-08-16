"""Synthetic eval-case generation: a concrete ``GenerateEvaluateReflectBase`` agent.

``EvalCaseGenerator`` wires ``adk.generate_evaluate_reflect.base.GenerateEvaluateReflectBase``
around two Anthropic-backed roles - a generator that proposes a new candidate task for the
plan-then-act demo agent (``adk.demos.plan_then_act_demo``, two tools: ``web_search`` and
``calculate``), and an evaluator that critiques each candidate against a fixed rubric
(realistic, unambiguous, genuinely requires exactly the tool(s) it claims) via forced
tool-use. No third LLM role for reflection: the evaluator's own rejection rationale already
says what's wrong with a candidate, so it's reused directly as ``reflection_feedback`` (see
``_RationaleReflector``).

``EvalCaseGenerator.generate_eval_cases()`` is the specific synthetic-data-generation use
case built on top of the generic base class: it drives ``EXAMPLES_PER_SEED`` independent GER
runs per seed case (mirroring the hand-written cases in
``docs/demos/eval_plan_then_act_demo.ipynb``), producing up to ``3 * EXAMPLES_PER_SEED``
accepted cases. Seeds and counts are fixed constants rather than configurable inputs, matching
this demo's minimal scope. A seed run that exhausts its attempt budget without a pass is
skipped rather than failing the whole batch.

See ``docs/demos/generate_eval_cases_demo.ipynb`` for a walkthrough that imports this module,
runs it against the live Anthropic API, and writes the result to
``docs/demos/data/generated_eval_cases.json``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal, cast

from anthropic import Anthropic
from anthropic.types import ToolChoiceToolParam, ToolParam
from langchain_core.runnables import Runnable
from langchain_core.runnables.config import RunnableConfig
from pydantic import BaseModel
from typing_extensions import override

from ..anthropic_client import get_anthropic_client
from ..anthropic_runnables import AnthropicRunnable
from ..eval_harness.cases import EvalCase, ExpectedStep
from ..generate_evaluate_reflect.base import GenerateEvaluateReflectBase
from ..generate_evaluate_reflect.config import GenerateEvaluateReflectConfig

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5"

# Resolved from this file's location (not cwd) since the notebook that calls dump_eval_cases
# with this path runs with its own directory as cwd, not the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_PATH = _REPO_ROOT / "docs" / "demos" / "data" / "generated_eval_cases.json"

EXAMPLES_PER_SEED = 2
MAX_ATTEMPTS = 3

# Mirrors the three hand-written cases in docs/demos/eval_plan_then_act_demo.ipynb, one per
# tool-routing category the plan-then-act demo agent needs to get right.
SEED_CASES: list[EvalCase] = [
    EvalCase(
        id="search_only",
        task="What is the current population of France?",
        expected_steps=[ExpectedStep(executor_id="search", tool_name="web_search")],
    ),
    EvalCase(
        id="calc_only",
        task="What is 482 times 17?",
        expected_steps=[ExpectedStep(executor_id="calc", tool_name="calculate")],
    ),
    EvalCase(
        id="combined",
        task=(
            "Look up the current population of France and Germany, then calculate their "
            "combined population."
        ),
        expected_steps=[
            ExpectedStep(executor_id="search", tool_name="web_search"),
            ExpectedStep(executor_id="search", tool_name="web_search"),
            ExpectedStep(executor_id="calc", tool_name="calculate"),
        ],
    ),
]

_TOOLS_DESCRIPTION = """\
The agent under test has two executors, each owning one tool:

- executor_id="search", tool_name="web_search" - a live web search; use it for tasks that need
  a real-world fact (a current statistic, price, event, etc.) that can't be answered from
  general knowledge alone.
- executor_id="calc", tool_name="calculate" - a sandboxed arithmetic evaluator; use it for tasks
  that need numeric computation.
"""

_PROPOSE_EVAL_CASE_TOOL_NAME = "propose_eval_case"


class _GeneratedCandidate(BaseModel):
    """Shape a ``propose_eval_case`` tool call must match."""

    task: str
    expected_steps: list[ExpectedStep]


_PROPOSE_EVAL_CASE_TOOL = cast(
    ToolParam,
    {
        "name": _PROPOSE_EVAL_CASE_TOOL_NAME,
        "description": "Propose one new eval-case task and the tool-routing it should require.",
        "input_schema": _GeneratedCandidate.model_json_schema(),
    },
)
_PROPOSE_EVAL_CASE_TOOL_CHOICE = cast(
    ToolChoiceToolParam,
    {"type": "tool", "name": _PROPOSE_EVAL_CASE_TOOL_NAME},
)

GENERATOR_SYSTEM_PROMPT = f"""\
You write eval cases for testing a plan-then-act agent.

{_TOOLS_DESCRIPTION}
You will be given, as JSON, a "context.seed" example: a task plus the expected_steps it should
route to. Propose ONE new task via the {_PROPOSE_EVAL_CASE_TOOL_NAME} tool whose expected_steps
have the SAME tool-routing shape as the seed's (same executors, same tool_names, same count and
order) - that shape is what defines this category, so matching it is expected and required. What
must differ is the real-world subject: pick different entities/topics and different numbers than
both "context.seed" and every task listed in "context.already_generated" - not the same
countries, companies, quantities, etc., even reworded.

If the input includes "reflection_feedback", it is a critique of your previous attempt for this
same seed - fix the specific problem it describes.
"""


def _parse_generated_candidate(response: Any) -> dict[str, Any]:
    for block in response.content:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == _PROPOSE_EVAL_CASE_TOOL_NAME
        ):
            candidate = _GeneratedCandidate.model_validate(block.input)
            return {"candidate": candidate.model_dump()}
    raise ValueError(
        f"Anthropic response did not include a {_PROPOSE_EVAL_CASE_TOOL_NAME!r} tool_use block",
    )


def build_eval_case_generator(
    client: Anthropic,
    *,
    model: str = DEFAULT_MODEL,
) -> Runnable[dict[str, Any], dict[str, Any]]:
    """Build the generator Runnable: proposes one candidate ``{task, expected_steps}`` per call."""
    return AnthropicRunnable(
        client,
        model=model,
        system_prompt=GENERATOR_SYSTEM_PROMPT,
        tools=[_PROPOSE_EVAL_CASE_TOOL],
        tool_choice=_PROPOSE_EVAL_CASE_TOOL_CHOICE,
        response_parser=_parse_generated_candidate,
    )


_SUBMIT_VERDICT_TOOL_NAME = "submit_verdict"


class _Verdict(BaseModel):
    """Shape a ``submit_verdict`` tool call must match."""

    verdict: Literal["pass", "fail"]
    rationale: str


_SUBMIT_VERDICT_TOOL = cast(
    ToolParam,
    {
        "name": _SUBMIT_VERDICT_TOOL_NAME,
        "description": "Submit an accept/reject verdict on the candidate eval case.",
        "input_schema": _Verdict.model_json_schema(),
    },
)
_SUBMIT_VERDICT_TOOL_CHOICE = cast(
    ToolChoiceToolParam,
    {"type": "tool", "name": _SUBMIT_VERDICT_TOOL_NAME},
)

EVALUATOR_SYSTEM_PROMPT = f"""\
You review candidate eval cases for testing a plan-then-act agent.

{_TOOLS_DESCRIPTION}
You will be given, as JSON, "context.seed" (the seed this candidate was generated from),
"context.already_generated" (tasks already accepted for this seed), and "candidate" (a
{{task, expected_steps}} pair to review). Submit a verdict via the {_SUBMIT_VERDICT_TOOL_NAME}
tool. Reject (verdict="fail") unless ALL of the following hold, and say specifically which one
failed in "rationale":

1. The task is realistic and unambiguous - a person could act on it without guessing intent.
2. It genuinely requires exactly the tools listed in expected_steps: no more (e.g. an
   unnecessary calc step) and no fewer (e.g. a fact it claims is general knowledge but actually
   needs a lookup).
3. expected_steps has the same tool-routing shape as context.seed's (same executors, same
   tool_names, same count and order) - matching the seed's shape is expected and required, since
   that shape is what defines this category; it is NOT a reason to reject.
4. Its real-world subject (entities, topics, quantities) is genuinely different from both
   context.seed's task and every task in context.already_generated - not the same
   countries/companies/numbers reworded. Sharing the seed's tool-routing shape (criterion 3) is
   fine and expected; only a repeated *subject* is a problem.
"""


def _parse_verdict(response: Any) -> dict[str, Any]:
    for block in response.content:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == _SUBMIT_VERDICT_TOOL_NAME
        ):
            verdict = _Verdict.model_validate(block.input)
            return {"eval_verdict": verdict.verdict, "eval_rationale": verdict.rationale}
    raise ValueError(
        f"Anthropic response did not include a {_SUBMIT_VERDICT_TOOL_NAME!r} tool_use block",
    )


def build_eval_case_evaluator(
    client: Anthropic,
    *,
    model: str = DEFAULT_MODEL,
) -> Runnable[dict[str, Any], dict[str, Any]]:
    """Build the evaluator Runnable: critiques a candidate and returns a pass/fail verdict."""
    return AnthropicRunnable(
        client,
        model=model,
        system_prompt=EVALUATOR_SYSTEM_PROMPT,
        tools=[_SUBMIT_VERDICT_TOOL],
        tool_choice=_SUBMIT_VERDICT_TOOL_CHOICE,
        response_parser=_parse_verdict,
    )


class _RationaleReflector(Runnable[dict[str, Any], dict[str, Any]]):
    """Reflector that reuses the evaluator's own rejection rationale as next-attempt feedback.

    No separate LLM call: the evaluator's ``eval_rationale`` on a "fail" verdict already names
    the specific problem, which is exactly what a reflect step would otherwise have to
    re-derive.
    """

    @override
    def invoke(
        self,
        input: dict[str, Any],
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {"reflection_feedback": input.get("eval_rationale")}


class EvalCaseGenerator(GenerateEvaluateReflectBase):
    """Concrete GER agent: synthesizes eval cases for ``DemoPlanThenActAgent``."""

    def __init__(
        self,
        *,
        client: Anthropic | None = None,
        model: str = DEFAULT_MODEL,
        config: GenerateEvaluateReflectConfig | None = None,
    ) -> None:
        self._client = client or get_anthropic_client()
        self._model = model
        super().__init__(config=config or GenerateEvaluateReflectConfig(max_attempts=MAX_ATTEMPTS))

    @property
    def variant(self) -> str:
        return "generate_eval_cases_demo"

    def _build_generator(self) -> Runnable[dict[str, Any], dict[str, Any]]:
        return build_eval_case_generator(self._client, model=self._model)

    def _build_evaluator(self) -> Runnable[dict[str, Any], dict[str, Any]]:
        return build_eval_case_evaluator(self._client, model=self._model)

    def _build_reflector(self) -> Runnable[dict[str, Any], dict[str, Any]]:
        return _RationaleReflector()

    def _input_to_state(self, input: dict[str, Any]) -> dict[str, Any]:
        return {"task": input["task"], "context": input.get("context", {})}

    def generate_eval_cases(
        self,
        *,
        seeds: list[EvalCase] = SEED_CASES,
        examples_per_seed: int = EXAMPLES_PER_SEED,
    ) -> list[EvalCase]:
        """Run the GER loop ``examples_per_seed`` times per seed, collecting accepted cases.

        Already-accepted tasks for a seed are passed back in as ``context.already_generated``
        so later runs for that same seed don't just repeat it. A seed run that exhausts its
        attempt budget without an accepted candidate is logged and skipped, so one stubborn
        seed can't fail the whole batch.
        """
        cases: list[EvalCase] = []
        for seed in seeds:
            already_generated: list[str] = []
            for attempt in range(1, examples_per_seed + 1):
                out = self.invoke(
                    {
                        "task": f"Generate a new eval case in the {seed.id!r} category.",
                        "context": {
                            "seed": seed.model_dump(),
                            "already_generated": list(already_generated),
                        },
                    },
                )
                accepted = out.get("accepted_artifact")
                if accepted is None:
                    logger.warning(
                        "seed %r run %s/%s exhausted %s attempts without a pass",
                        seed.id,
                        attempt,
                        examples_per_seed,
                        self.config.max_attempts,
                    )
                    continue
                already_generated.append(accepted["task"])
                cases.append(
                    EvalCase(
                        id=f"generated_{seed.id}_{attempt}",
                        task=accepted["task"],
                        expected_steps=[
                            ExpectedStep.model_validate(step)
                            for step in accepted.get("expected_steps", [])
                        ],
                    ),
                )
        return cases
