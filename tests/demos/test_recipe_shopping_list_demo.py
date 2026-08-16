from __future__ import annotations

from typing import Any

from adk.demos.recipe_shopping_list_demo import (
    RecipeShoppingListAgent,
    _RationaleReflector,
    _ShoppingListConsistencyEvaluator,
)

_PASSING_CANDIDATE = {
    "recipe": {
        "name": "Weeknight Chicken Tikka Masala",
        "servings": "4",
        "ingredients": [
            {"name": "chicken thighs", "quantity": "1.5", "unit": "lb"},
            {"name": "garam masala", "quantity": "2", "unit": "tsp"},
        ],
        "instructions": ["Marinate the chicken.", "Simmer in sauce."],
    },
    "shopping_list": [
        {"name": "Chicken Thighs", "quantity": "1.5", "unit": "lb"},
        {"name": " garam masala ", "quantity": "2", "unit": "tsp"},
    ],
}


class _FakeClassifier:
    def __init__(self, output: dict[str, Any]) -> None:
        self._output = output
        self.calls: list[dict[str, Any]] = []

    def invoke(self, input: dict[str, Any], config: Any = None) -> dict[str, Any]:
        self.calls.append(dict(input))
        return self._output


class _FakeGenerator:
    def __init__(self, candidate: dict[str, Any]) -> None:
        self._candidate = candidate
        self.calls: list[dict[str, Any]] = []

    def invoke(self, input: dict[str, Any], config: Any = None) -> dict[str, Any]:
        self.calls.append(dict(input))
        return {"candidate": self._candidate}


class _TestRecipeShoppingListAgent(RecipeShoppingListAgent):
    """Test double: same graph wiring/``handle_request`` logic, fake LLM roles.

    Bypasses ``RecipeShoppingListAgent.__init__`` (which would build a real Anthropic client) by
    calling the base class's ``__init__`` directly - ``_build_generator``/``_build_evaluator``/
    ``handle_request``'s classifier are all overridden or injected below, so ``self._client``/
    ``self._model`` are never touched.
    """

    def __init__(
        self,
        *,
        classifier: _FakeClassifier,
        generator: _FakeGenerator,
        search_results: list[dict[str, Any]] | None = None,
    ) -> None:
        self._classifier = classifier
        self._generator = generator
        self._search_results = search_results or []
        super(RecipeShoppingListAgent, self).__init__()  # type: ignore[misc]

    def _build_generator(self) -> _FakeGenerator:  # type: ignore[override]
        return self._generator

    def _build_evaluator(self) -> _ShoppingListConsistencyEvaluator:  # type: ignore[override]
        return _ShoppingListConsistencyEvaluator()

    def _build_reflector(self) -> _RationaleReflector:  # type: ignore[override]
        return _RationaleReflector()

    def handle_request(self, user_message: str) -> dict[str, Any]:
        classification = self._classifier.invoke({"message": user_message})
        if not classification.get("in_scope"):
            return {
                "refused": True,
                "message": classification.get("refusal_message") or "refused",
            }
        dish = classification["dish"]
        out = self.invoke(
            {
                "task": f"Develop a recipe for {dish}.",
                "context": {"dish": dish, "search_results": self._search_results},
            },
        )
        return {"refused": False, "dish": dish, "search_results": self._search_results, **out}


def test_handle_request_refuses_out_of_scope_requests_without_running_the_loop() -> None:
    classifier = _FakeClassifier(
        {"in_scope": False, "dish": None, "refusal_message": "I only do recipes."},
    )
    generator = _FakeGenerator(_PASSING_CANDIDATE)
    agent = _TestRecipeShoppingListAgent(classifier=classifier, generator=generator)

    out = agent.handle_request("write me a poem about spring")

    assert out == {"refused": True, "message": "I only do recipes."}
    assert generator.calls == []


def test_handle_request_runs_the_loop_and_returns_accepted_recipe_for_in_scope_requests() -> None:
    classifier = _FakeClassifier({"in_scope": True, "dish": "chicken tikka masala"})
    generator = _FakeGenerator(_PASSING_CANDIDATE)
    agent = _TestRecipeShoppingListAgent(
        classifier=classifier,
        generator=generator,
        search_results=[{"title": "t", "url": "u", "snippet": "s"}],
    )

    out = agent.handle_request("find me a recipe for chicken tikka masala")

    assert out["refused"] is False
    assert out["dish"] == "chicken tikka masala"
    assert out["stop_reason"] == "all_pass"
    assert out["accepted_artifact"] == _PASSING_CANDIDATE
    assert generator.calls[0]["context"]["dish"] == "chicken tikka masala"


def test_shopping_list_evaluator_passes_when_names_match_up_to_normalization() -> None:
    evaluator = _ShoppingListConsistencyEvaluator()

    out = evaluator.invoke({"candidate": _PASSING_CANDIDATE})

    assert out["eval_verdict"] == "pass"


def test_shopping_list_evaluator_fails_on_missing_extra_and_duplicate_items() -> None:
    evaluator = _ShoppingListConsistencyEvaluator()
    candidate = {
        "recipe": {
            "name": "Test Dish",
            "ingredients": [
                {"name": "flour", "quantity": "1", "unit": "cup"},
                {"name": "sugar", "quantity": "1", "unit": "cup"},
            ],
            "instructions": ["Mix."],
        },
        "shopping_list": [
            {"name": "sugar", "quantity": "1", "unit": "cup"},
            {"name": "sugar", "quantity": "1", "unit": "cup"},
            {"name": "butter", "quantity": "1", "unit": "stick"},
        ],
    }

    out = evaluator.invoke({"candidate": candidate})

    assert out["eval_verdict"] == "fail"
    assert "flour" in out["eval_rationale"]
    assert "butter" in out["eval_rationale"]
    assert "sugar" in out["eval_rationale"]


def test_rationale_reflector_reuses_eval_rationale_as_feedback() -> None:
    reflector = _RationaleReflector()

    out = reflector.invoke({"eval_rationale": "missing from shopping list: flour"})

    assert out == {"reflection_feedback": "missing from shopping list: flour"}
