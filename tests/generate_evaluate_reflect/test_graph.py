from __future__ import annotations

from typing import Any

from adk.generate_evaluate_reflect.graph import (
    build_ger_closed_loop_graph,
    logical_graph_node_ids,
)


class _FakeGenerator:
    def __init__(self, candidates: list[dict[str, Any]]) -> None:
        self._candidates = candidates
        self.calls: list[dict[str, Any]] = []

    def invoke(self, input: dict[str, Any], config: Any = None) -> dict[str, Any]:
        self.calls.append(dict(input))
        index = len(self.calls) - 1
        return {"candidate": self._candidates[min(index, len(self._candidates) - 1)]}


class _FakeEvaluator:
    def __init__(self, verdicts: list[str]) -> None:
        self._verdicts = verdicts
        self.calls: list[dict[str, Any]] = []

    def invoke(self, input: dict[str, Any], config: Any = None) -> dict[str, Any]:
        self.calls.append(dict(input))
        index = len(self.calls) - 1
        verdict = self._verdicts[min(index, len(self._verdicts) - 1)]
        return {"eval_verdict": verdict, "eval_rationale": f"attempt {index + 1}: {verdict}"}


class _FakeReflector:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def invoke(self, input: dict[str, Any], config: Any = None) -> dict[str, Any]:
        self.calls.append(dict(input))
        return {"reflection_feedback": f"fix issue from attempt {len(self.calls)}"}


def _build_graph(
    *,
    generator: _FakeGenerator,
    evaluator: _FakeEvaluator,
    reflector: _FakeReflector | None = None,
) -> Any:
    return build_ger_closed_loop_graph(
        generator=generator,
        evaluator=evaluator,
        reflector=reflector or _FakeReflector(),
    )


def test_accept_path_terminates_immediately_without_reflecting() -> None:
    generator = _FakeGenerator([{"draft": "v1"}])
    evaluator = _FakeEvaluator(["pass"])
    reflector = _FakeReflector()
    compiled = _build_graph(generator=generator, evaluator=evaluator, reflector=reflector)

    out = compiled.invoke({"task": "write a haiku", "context": {}})

    assert out["accepted_artifact"] == {"draft": "v1"}
    assert out["stop_reason"] == "all_pass"
    assert out["attempt_index"] == 1
    assert len(out["attempts"]) == 1
    assert reflector.calls == []


def test_reject_path_loops_and_increments_attempt_index_and_feedback() -> None:
    generator = _FakeGenerator([{"draft": "v1"}, {"draft": "v2"}])
    evaluator = _FakeEvaluator(["fail", "pass"])
    reflector = _FakeReflector()
    compiled = _build_graph(generator=generator, evaluator=evaluator, reflector=reflector)

    out = compiled.invoke({"task": "write a haiku", "context": {}})

    assert out["accepted_artifact"] == {"draft": "v2"}
    assert out["stop_reason"] == "all_pass"
    assert out["attempt_index"] == 2
    assert [a["candidate"] for a in out["attempts"]] == [{"draft": "v1"}, {"draft": "v2"}]
    assert len(reflector.calls) == 1
    assert out["reflection_feedback"] == "fix issue from attempt 1"
    assert generator.calls[1]["reflection_feedback"] == "fix issue from attempt 1"


def test_attempt_cap_forces_exit_without_hanging() -> None:
    generator = _FakeGenerator([{"draft": "v1"}, {"draft": "v2"}])
    evaluator = _FakeEvaluator(["fail", "fail"])
    reflector = _FakeReflector()
    compiled = _build_graph(generator=generator, evaluator=evaluator, reflector=reflector)

    out = compiled.invoke({"task": "write a haiku", "context": {}, "max_attempts": 2})

    assert out["accepted_artifact"] is None
    assert out["stop_reason"] == "budget_exhausted"
    assert out["attempt_index"] == 2
    assert len(out["attempts"]) == 2
    assert len(reflector.calls) == 1


def test_build_ger_closed_loop_graph_exposes_expected_node_ids() -> None:
    compiled = _build_graph(
        generator=_FakeGenerator([{"draft": "v1"}]),
        evaluator=_FakeEvaluator(["pass"]),
    )

    assert set(logical_graph_node_ids(compiled)) == {"generate", "evaluate", "reflect", "sink"}
