from __future__ import annotations

from typing import Any

from adk.demos.generate_eval_cases_demo import _RationaleReflector, generate_eval_cases
from adk.eval_harness.cases import EvalCase, ExpectedStep

_SEEDS = [
    EvalCase(
        id="search_only",
        task="seed search task",
        expected_steps=[ExpectedStep(executor_id="search", tool_name="web_search")],
    ),
    EvalCase(
        id="calc_only",
        task="seed calc task",
        expected_steps=[ExpectedStep(executor_id="calc", tool_name="calculate")],
    ),
]


class _FakeGenerator:
    """Always proposes a candidate named after the seed and how many times it's been called."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def invoke(self, input: dict[str, Any], config: Any = None) -> dict[str, Any]:
        self.calls.append(dict(input))
        seed_id = input["context"]["seed"]["id"]
        return {
            "candidate": {
                "task": f"generated task for {seed_id} (call {len(self.calls)})",
                "expected_steps": input["context"]["seed"]["expected_steps"],
            },
        }


class _FakeEvaluator:
    def __init__(self, verdicts_by_seed: dict[str, list[str]]) -> None:
        self._verdicts_by_seed = verdicts_by_seed
        self._counts: dict[str, int] = {}

    def invoke(self, input: dict[str, Any], config: Any = None) -> dict[str, Any]:
        seed_id = input["context"]["seed"]["id"]
        index = self._counts.get(seed_id, 0)
        self._counts[seed_id] = index + 1
        verdict = self._verdicts_by_seed[seed_id][index]
        return {"eval_verdict": verdict, "eval_rationale": f"{seed_id} attempt {index + 1}"}


def test_generates_examples_per_seed_cases_when_all_pass() -> None:
    generator = _FakeGenerator()
    evaluator = _FakeEvaluator({"search_only": ["pass"] * 2, "calc_only": ["pass"] * 2})

    cases = generate_eval_cases(
        generator=generator,
        evaluator=evaluator,
        reflector=_RationaleReflector(),
        seeds=_SEEDS,
        examples_per_seed=2,
        max_attempts=3,
    )

    assert [case.id for case in cases] == [
        "generated_search_only_1",
        "generated_search_only_2",
        "generated_calc_only_1",
        "generated_calc_only_2",
    ]
    assert all(isinstance(case, EvalCase) for case in cases)
    assert cases[0].expected_steps == [ExpectedStep(executor_id="search", tool_name="web_search")]


def test_skips_seed_that_exhausts_attempt_budget_without_a_pass() -> None:
    generator = _FakeGenerator()
    evaluator = _FakeEvaluator({"search_only": ["fail", "fail"], "calc_only": ["pass"]})

    cases = generate_eval_cases(
        generator=generator,
        evaluator=evaluator,
        reflector=_RationaleReflector(),
        seeds=_SEEDS,
        examples_per_seed=1,
        max_attempts=2,
    )

    assert [case.id for case in cases] == ["generated_calc_only_1"]


def test_rationale_reflector_reuses_eval_rationale_as_feedback() -> None:
    reflector = _RationaleReflector()

    out = reflector.invoke({"eval_rationale": "needs a real lookup, not general knowledge"})

    assert out == {"reflection_feedback": "needs a real lookup, not general knowledge"}
