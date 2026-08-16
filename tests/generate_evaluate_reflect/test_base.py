from __future__ import annotations

from typing import Any

import pytest

from adk.generate_evaluate_reflect.base import GenerateEvaluateReflectBase
from adk.generate_evaluate_reflect.config import GenerateEvaluateReflectConfig


class _FakeRole:
    def __init__(self, outputs: list[dict[str, Any]]) -> None:
        self._outputs = outputs
        self.calls: list[dict[str, Any]] = []

    def invoke(self, input: dict[str, Any], config: Any = None) -> dict[str, Any]:
        self.calls.append(dict(input))
        return self._outputs[min(len(self.calls) - 1, len(self._outputs) - 1)]


class _FakeGerAgent(GenerateEvaluateReflectBase):
    def __init__(
        self,
        *,
        generator: _FakeRole,
        evaluator: _FakeRole,
        reflector: _FakeRole,
        config: GenerateEvaluateReflectConfig | None = None,
    ) -> None:
        self._generator = generator
        self._evaluator = evaluator
        self._reflector = reflector
        super().__init__(config=config)

    @property
    def variant(self) -> str:
        return "fake_ger_agent"

    def _build_generator(self) -> _FakeRole:
        return self._generator

    def _build_evaluator(self) -> _FakeRole:
        return self._evaluator

    def _build_reflector(self) -> _FakeRole:
        return self._reflector

    def _input_to_state(self, input: dict[str, Any]) -> dict[str, Any]:
        state = {"task": input["task"], "context": input.get("context", {})}
        if "max_attempts" in input:
            state["max_attempts"] = input["max_attempts"]
        return state


def test_invoke_maps_input_and_runs_graph_to_acceptance() -> None:
    generator = _FakeRole([{"candidate": {"draft": "v1"}}])
    evaluator = _FakeRole([{"eval_verdict": "pass", "eval_rationale": "ok"}])
    reflector = _FakeRole([{"reflection_feedback": "n/a"}])
    agent = _FakeGerAgent(generator=generator, evaluator=evaluator, reflector=reflector)

    out = agent.invoke({"task": "write a haiku", "context": {"topic": "autumn"}})

    assert out["accepted_artifact"] == {"draft": "v1"}
    assert out["stop_reason"] == "all_pass"
    assert generator.calls[0]["task"] == "write a haiku"
    assert generator.calls[0]["context"] == {"topic": "autumn"}


def test_invoke_fills_in_max_attempts_from_config_when_absent() -> None:
    generator = _FakeRole([{"candidate": {"draft": f"v{i}"}} for i in range(1, 4)])
    evaluator = _FakeRole([{"eval_verdict": "fail", "eval_rationale": "no"}] * 3)
    reflector = _FakeRole([{"reflection_feedback": "try again"}] * 3)
    agent = _FakeGerAgent(
        generator=generator,
        evaluator=evaluator,
        reflector=reflector,
        config=GenerateEvaluateReflectConfig(max_attempts=2),
    )

    out = agent.invoke({"task": "write a haiku"})

    assert out["stop_reason"] == "budget_exhausted"
    assert out["attempt_index"] == 2


def test_invoke_respects_explicit_max_attempts_in_input() -> None:
    generator = _FakeRole([{"candidate": {"draft": f"v{i}"}} for i in range(1, 4)])
    evaluator = _FakeRole([{"eval_verdict": "fail", "eval_rationale": "no"}] * 3)
    reflector = _FakeRole([{"reflection_feedback": "try again"}] * 3)
    agent = _FakeGerAgent(generator=generator, evaluator=evaluator, reflector=reflector)

    out = agent.invoke({"task": "write a haiku", "max_attempts": 1})

    assert out["stop_reason"] == "budget_exhausted"
    assert out["attempt_index"] == 1


def test_get_compiled_graph_exposes_the_compiled_graph() -> None:
    agent = _FakeGerAgent(
        generator=_FakeRole([{"candidate": {"draft": "v1"}}]),
        evaluator=_FakeRole([{"eval_verdict": "pass", "eval_rationale": "ok"}]),
        reflector=_FakeRole([{"reflection_feedback": "n/a"}]),
    )

    assert set(agent.get_compiled_graph().get_graph().nodes) >= {
        "generate",
        "evaluate",
        "reflect",
        "sink",
    }


def test_base_class_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        GenerateEvaluateReflectBase()  # type: ignore[abstract]
