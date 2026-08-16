from __future__ import annotations

from typing import Any

from adk.demos.generate_eval_cases_demo import EvalCaseGenerator, _RationaleReflector
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


class _TestEvalCaseGenerator(EvalCaseGenerator):
    """Test double: same ``_input_to_state``/``generate_eval_cases`` logic, fake LLM roles.

    Bypasses ``EvalCaseGenerator.__init__`` (which would build a real Anthropic client) by
    calling the base class's ``__init__`` directly - ``_build_generator``/``_build_evaluator``
    are overridden below, so ``self._client``/``self._model`` are never touched.
    """

    def __init__(self, *, generator: _FakeGenerator, evaluator: _FakeEvaluator) -> None:
        self._generator = generator
        self._evaluator = evaluator
        super(EvalCaseGenerator, self).__init__()  # type: ignore[misc]

    def _build_generator(self) -> _FakeGenerator:  # type: ignore[override]
        return self._generator

    def _build_evaluator(self) -> _FakeEvaluator:  # type: ignore[override]
        return self._evaluator

    def _build_reflector(self) -> _RationaleReflector:  # type: ignore[override]
        return _RationaleReflector()


def test_generates_examples_per_seed_cases_when_all_pass() -> None:
    agent = _TestEvalCaseGenerator(
        generator=_FakeGenerator(),
        evaluator=_FakeEvaluator({"search_only": ["pass"] * 2, "calc_only": ["pass"] * 2}),
    )

    cases = agent.generate_eval_cases(seeds=_SEEDS, examples_per_seed=2)

    assert [case.id for case in cases] == [
        "generated_search_only_1",
        "generated_search_only_2",
        "generated_calc_only_1",
        "generated_calc_only_2",
    ]
    assert all(isinstance(case, EvalCase) for case in cases)
    assert cases[0].expected_steps == [ExpectedStep(executor_id="search", tool_name="web_search")]


def test_skips_seed_that_exhausts_attempt_budget_without_a_pass() -> None:
    agent = _TestEvalCaseGenerator(
        generator=_FakeGenerator(),
        evaluator=_FakeEvaluator({"search_only": ["fail", "fail", "fail"], "calc_only": ["pass"]}),
    )

    cases = agent.generate_eval_cases(seeds=_SEEDS, examples_per_seed=1)

    assert [case.id for case in cases] == ["generated_calc_only_1"]


def test_rationale_reflector_reuses_eval_rationale_as_feedback() -> None:
    reflector = _RationaleReflector()

    out = reflector.invoke({"eval_rationale": "needs a real lookup, not general knowledge"})

    assert out == {"reflection_feedback": "needs a real lookup, not general knowledge"}
