from __future__ import annotations

from adk.planner_executor.state import (
    PlanThenActArtifact,
    PlanThenActStep,
    authorize_plan_from_artifact,
)


def _artifact(*tool_names: str) -> PlanThenActArtifact:
    return PlanThenActArtifact(
        steps=[
            PlanThenActStep(executor_id="search", tool_name=name, tool_args={"q": name})
            for name in tool_names
        ],
    )


def test_authorize_plan_from_artifact_pulls_from_state_plan_artifact() -> None:
    artifact = _artifact("web_search")

    out = authorize_plan_from_artifact({"plan_artifact": artifact})

    assert out["authorized_plan"] is artifact
    assert out["authorized_steps"] == artifact.steps


def test_authorize_plan_from_artifact_uses_explicit_validated_override() -> None:
    state_artifact = _artifact("web_search")
    validated_artifact = _artifact("calculate", "web_search")

    out = authorize_plan_from_artifact(
        {"plan_artifact": state_artifact},
        validated=validated_artifact,
    )

    assert out["authorized_plan"] is validated_artifact
    assert out["authorized_steps"] == validated_artifact.steps


def test_authorize_plan_from_artifact_handles_missing_plan_artifact() -> None:
    out = authorize_plan_from_artifact({})

    assert out["authorized_plan"] is None
    assert out["authorized_steps"] == []
