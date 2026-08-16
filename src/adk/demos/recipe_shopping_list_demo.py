"""End-to-end recipe + shopping list demo: a guarded, research-grounded GER agent.

Wires ``adk.generate_evaluate_reflect``'s closed-loop retry building blocks around a narrow,
single-purpose product: given the name of a dish, research a handful of existing recipes for
it, synthesize one new recipe from comparing and contrasting them, and build a shopping list
for that recipe. Two things distinguish this demo from
``adk.demos.generate_eval_cases_demo.EvalCaseGenerator``, the repo's other concrete
``GenerateEvaluateReflectBase`` subclass:

- **A guardrail ahead of the loop.** The agent's only supported request shape is "a recipe (and
  shopping list) for one named dish" - anything else is refused with a statement of what the
  agent can do, via ``_RequestClassifier``, an ``AnthropicRunnable`` gate that runs in
  ``RecipeShoppingListAgent.handle_request`` *before* the GER graph is ever invoked. There's no
  hook for a pre-generate node in ``build_ger_closed_loop_graph``'s fixed topology, so the gate
  lives outside the graph, same as ``search_existing_recipes`` below.
- **A deterministic evaluator.** "Does the shopping list match the recipe, with no duplicates?"
  is a mechanical set comparison, not a judgment call, so ``_ShoppingListConsistencyEvaluator``
  is a plain Python ``Runnable`` with no LLM call in it at all - proof that ``evaluate`` in this
  pattern is any ``Runnable`` returning ``eval_verdict``/``eval_rationale``, not necessarily
  another model call. Its rejection rationale is reused directly as reflection feedback (see
  ``_RationaleReflector``, the same reuse-the-rationale move
  ``generate_eval_cases_demo._RationaleReflector`` makes for its own, LLM-backed evaluator).

Research (``search_existing_recipes``) runs once per request, outside the retry loop: the
generator gets the same 3-5 real recipes as context on every attempt, and only the synthesis
(and, on retry, the shopping-list fix) changes - re-searching on every reflect pass would just
add latency without changing what there is to compare and contrast.

See ``docs/demos/recipe_shopping_list_demo.ipynb`` for a walkthrough that imports this module
and runs it against the live Anthropic + Tavily APIs.

Requires ``ANTHROPIC_API_KEY`` and ``TAVILY_API_KEY`` (see README's Setup section).

Usage::

    uv run python -m adk.demos.recipe_shopping_list_demo
    uv run python -m adk.demos.recipe_shopping_list_demo "<custom request>"
"""

from __future__ import annotations

import argparse
from collections import Counter
from typing import Any, cast

from anthropic import Anthropic
from anthropic.types import ToolChoiceToolParam, ToolParam
from dotenv import load_dotenv
from langchain_core.runnables import Runnable
from langchain_core.runnables.config import RunnableConfig
from pydantic import BaseModel
from typing_extensions import override

from ..anthropic_client import get_anthropic_client
from ..anthropic_runnables import AnthropicRunnable
from ..generate_evaluate_reflect.base import GenerateEvaluateReflectBase
from ..generate_evaluate_reflect.config import GenerateEvaluateReflectConfig
from ..search_client import get_search_client

DEFAULT_MODEL = "claude-sonnet-5"

DEFAULT_REQUEST = "Find me a recipe for chicken tikka masala and put together a shopping list."

MAX_ATTEMPTS = 3
_SEARCH_MAX_RESULTS = 5

_DEFAULT_REFUSAL_MESSAGE = (
    "I can only research and develop a recipe - with a shopping list - for one dish you name. "
    "Try something like 'find me a recipe for chicken tikka masala.'"
)


def _normalize_name(name: str) -> str:
    """Fold an ingredient/shopping-list item name to a comparable key (case/whitespace only)."""
    return " ".join(name.strip().lower().split())


# --- Candidate shape: what the generator proposes and the evaluator checks ------------------


class Ingredient(BaseModel):
    """One recipe ingredient."""

    name: str
    quantity: str
    unit: str | None = None


class RecipeCandidate(BaseModel):
    """A synthesized recipe."""

    name: str
    servings: str | None = None
    ingredients: list[Ingredient]
    instructions: list[str]


class ShoppingListItem(BaseModel):
    """One consolidated shopping list line."""

    name: str
    quantity: str
    unit: str | None = None


class RecipeAndShoppingList(BaseModel):
    """Shape a ``propose_recipe_and_shopping_list`` tool call must match."""

    recipe: RecipeCandidate
    shopping_list: list[ShoppingListItem]


# --- Guardrail: refuse anything that isn't "a recipe for a named dish" ----------------------

_CLASSIFY_REQUEST_TOOL_NAME = "classify_request"


class _RequestClassification(BaseModel):
    """Shape a ``classify_request`` tool call must match."""

    in_scope: bool
    dish: str | None = None
    refusal_message: str | None = None


_CLASSIFY_REQUEST_TOOL = cast(
    ToolParam,
    {
        "name": _CLASSIFY_REQUEST_TOOL_NAME,
        "description": "Decide whether a user message is asking for a recipe + shopping list "
        "for one named dish, and extract the dish name if so.",
        "input_schema": _RequestClassification.model_json_schema(),
    },
)
_CLASSIFY_REQUEST_TOOL_CHOICE = cast(
    ToolChoiceToolParam,
    {"type": "tool", "name": _CLASSIFY_REQUEST_TOOL_NAME},
)

CLASSIFIER_SYSTEM_PROMPT = f"""\
You gate requests for a recipe-and-shopping-list agent. The agent's ONLY capability is: given
the name of a dish, research existing recipes for it, synthesize one new recipe, and build a
shopping list for that recipe.

Given the user's message (as JSON, under "message"), decide whether it is asking for exactly
that - a recipe (optionally also a shopping list) for ONE named dish. If so, set "in_scope" to
true, extract the dish name into "dish", and leave "refusal_message" null. Otherwise - a
different kind of request, no dish named, multiple unrelated dishes, or anything outside recipe
development - set "in_scope" to false, leave "dish" null, and set "refusal_message" to a short,
polite statement of what this agent can do, so the user knows how to rephrase.

Submit your decision via the {_CLASSIFY_REQUEST_TOOL_NAME} tool.
"""


def _parse_classification(response: Any) -> dict[str, Any]:
    for block in response.content:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == _CLASSIFY_REQUEST_TOOL_NAME
        ):
            classification = _RequestClassification.model_validate(block.input)
            return classification.model_dump()
    raise ValueError(
        f"Anthropic response did not include a {_CLASSIFY_REQUEST_TOOL_NAME!r} tool_use block",
    )


def build_request_classifier(
    client: Anthropic,
    *,
    model: str = DEFAULT_MODEL,
) -> Runnable[dict[str, Any], dict[str, Any]]:
    """Build the guardrail Runnable: in-scope check + dish extraction, or a refusal message."""
    return AnthropicRunnable(
        client,
        model=model,
        system_prompt=CLASSIFIER_SYSTEM_PROMPT,
        tools=[_CLASSIFY_REQUEST_TOOL],
        tool_choice=_CLASSIFY_REQUEST_TOOL_CHOICE,
        response_parser=_parse_classification,
    )


# --- Research: real recipes to compare and contrast, gathered outside the GER loop ----------


def search_existing_recipes(
    dish: str,
    *,
    max_results: int = _SEARCH_MAX_RESULTS,
) -> list[dict[str, Any]]:
    """Web search: find existing recipes for ``dish`` for the generator to compare and contrast."""
    client = get_search_client()
    response = client.search(query=f"{dish} recipe", max_results=max_results)
    return [
        {"title": r.get("title"), "url": r.get("url"), "snippet": r.get("content")}
        for r in (response.get("results") or [])[:max_results]
    ]


# --- Generator: compare and contrast the research into one new recipe + shopping list -------

_PROPOSE_RECIPE_TOOL_NAME = "propose_recipe_and_shopping_list"

_PROPOSE_RECIPE_TOOL = cast(
    ToolParam,
    {
        "name": _PROPOSE_RECIPE_TOOL_NAME,
        "description": "Propose one new recipe synthesized from the researched examples, plus "
        "a shopping list for it.",
        "input_schema": RecipeAndShoppingList.model_json_schema(),
    },
)
_PROPOSE_RECIPE_TOOL_CHOICE = cast(
    ToolChoiceToolParam,
    {"type": "tool", "name": _PROPOSE_RECIPE_TOOL_NAME},
)

GENERATOR_SYSTEM_PROMPT = f"""\
You are a recipe developer. You will be given, as JSON: "context.dish" (the dish to develop),
"context.search_results" (3-5 existing recipes for that dish, each a {{title, url, snippet}}
scraped from a real recipe site), and possibly "reflection_feedback" (a critique of your
previous attempt, if any).

Compare and contrast the search results - where they agree, where they diverge on ingredients,
quantities, or technique - and synthesize ONE new recipe that reflects the best of what you
found, not a copy of any single source. Then build its shopping list: one line per ingredient
the recipe uses, with a matching name, quantity, and unit. The shopping list must cover every
ingredient the recipe calls for, contain nothing the recipe doesn't use, and list each
ingredient exactly once (combine an ingredient used in multiple steps into a single line rather
than repeating it).

If "reflection_feedback" is present, it names a specific mismatch between the recipe and the
shopping list from your previous attempt - fix that specific problem.

Submit your recipe and shopping list via the {_PROPOSE_RECIPE_TOOL_NAME} tool.
"""


def _parse_generated_candidate(response: Any) -> dict[str, Any]:
    for block in response.content:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == _PROPOSE_RECIPE_TOOL_NAME
        ):
            candidate = RecipeAndShoppingList.model_validate(block.input)
            return {"candidate": candidate.model_dump()}
    raise ValueError(
        f"Anthropic response did not include a {_PROPOSE_RECIPE_TOOL_NAME!r} tool_use block",
    )


def build_recipe_generator(
    client: Anthropic,
    *,
    model: str = DEFAULT_MODEL,
) -> Runnable[dict[str, Any], dict[str, Any]]:
    """Build the generator Runnable: proposes one ``{recipe, shopping_list}`` candidate per call."""
    return AnthropicRunnable(
        client,
        model=model,
        system_prompt=GENERATOR_SYSTEM_PROMPT,
        tools=[_PROPOSE_RECIPE_TOOL],
        tool_choice=_PROPOSE_RECIPE_TOOL_CHOICE,
        max_tokens=4096,
        response_parser=_parse_generated_candidate,
    )


# --- Evaluator: deterministic set comparison, no LLM call needed ----------------------------


class _ShoppingListConsistencyEvaluator(Runnable[dict[str, Any], dict[str, Any]]):
    """Evaluator: shopping list must cover every recipe ingredient exactly once, nothing extra.

    A mechanical name comparison, not a judgment call - "does the list match the recipe" has a
    checkable right answer, so there's no need to spend an LLM call (or introduce a judge's own
    blind spots) verifying it.
    """

    @override
    def invoke(
        self,
        input: dict[str, Any],
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        candidate = input.get("candidate") or {}
        recipe = candidate.get("recipe") or {}
        ingredient_names = [_normalize_name(i["name"]) for i in recipe.get("ingredients", [])]
        shopping_names = [_normalize_name(i["name"]) for i in candidate.get("shopping_list", [])]

        missing = sorted(set(ingredient_names) - set(shopping_names))
        extra = sorted(set(shopping_names) - set(ingredient_names))
        duplicates = sorted(name for name, count in Counter(shopping_names).items() if count > 1)

        problems = []
        if missing:
            problems.append(f"missing from shopping list: {', '.join(missing)}")
        if extra:
            problems.append(f"shopping list items not used in the recipe: {', '.join(extra)}")
        if duplicates:
            problems.append(f"duplicate shopping list items: {', '.join(duplicates)}")

        if problems:
            return {"eval_verdict": "fail", "eval_rationale": "; ".join(problems)}
        return {
            "eval_verdict": "pass",
            "eval_rationale": "Shopping list covers every recipe ingredient exactly once, with "
            "no extras.",
        }


class _RationaleReflector(Runnable[dict[str, Any], dict[str, Any]]):
    """Reflector that reuses the evaluator's own rejection rationale as next-attempt feedback.

    No separate LLM call: ``_ShoppingListConsistencyEvaluator``'s ``eval_rationale`` on a "fail"
    verdict already names the specific mismatch, which is exactly what a reflect step would
    otherwise have to re-derive.
    """

    @override
    def invoke(
        self,
        input: dict[str, Any],
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {"reflection_feedback": input.get("eval_rationale")}


# --- The agent --------------------------------------------------------------------------------


class RecipeShoppingListAgent(GenerateEvaluateReflectBase):
    """Concrete GER agent: researches a dish, synthesizes a recipe, and verifies its shopping
    list matches it exactly (see module docstring for the guardrail and deterministic-evaluator
    design).
    """

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
        return "recipe_shopping_list_demo"

    def _build_generator(self) -> Runnable[dict[str, Any], dict[str, Any]]:
        return build_recipe_generator(self._client, model=self._model)

    def _build_evaluator(self) -> Runnable[dict[str, Any], dict[str, Any]]:
        return _ShoppingListConsistencyEvaluator()

    def _build_reflector(self) -> Runnable[dict[str, Any], dict[str, Any]]:
        return _RationaleReflector()

    def _input_to_state(self, input: dict[str, Any]) -> dict[str, Any]:
        return {"task": input["task"], "context": input.get("context", {})}

    def handle_request(self, user_message: str) -> dict[str, Any]:
        """Gate ``user_message``, then - if it's in scope - research and run the GER loop.

        Returns ``{"refused": True, "message": ...}`` for an out-of-scope request. Otherwise
        returns ``{"refused": False, "dish": ..., "search_results": ..., **graph_output}``,
        where ``graph_output`` is the same shape :meth:`invoke` returns (``accepted_artifact``,
        ``attempts``, ``stop_reason``, etc.).
        """
        classification = build_request_classifier(self._client, model=self._model).invoke(
            {"message": user_message},
        )
        if not classification.get("in_scope"):
            return {
                "refused": True,
                "message": classification.get("refusal_message") or _DEFAULT_REFUSAL_MESSAGE,
            }

        dish = cast(str, classification["dish"])
        search_results = search_existing_recipes(dish)
        out = self.invoke(
            {
                "task": f"Develop a recipe for {dish}.",
                "context": {"dish": dish, "search_results": search_results},
            },
        )
        return {"refused": False, "dish": dish, "search_results": search_results, **out}


def _print_recipe_and_shopping_list(artifact: dict[str, Any]) -> None:
    recipe = artifact["recipe"]
    print(f"Recipe: {recipe['name']}")
    if recipe.get("servings"):
        print(f"Servings: {recipe['servings']}")

    print("\nIngredients:")
    for ingredient in recipe["ingredients"]:
        unit = f" {ingredient['unit']}" if ingredient.get("unit") else ""
        print(f"  - {ingredient['quantity']}{unit} {ingredient['name']}")

    print("\nInstructions:")
    for i, step in enumerate(recipe["instructions"], start=1):
        print(f"  {i}. {step}")

    print("\nShopping list:")
    for item in artifact["shopping_list"]:
        unit = f" {item['unit']}" if item.get("unit") else ""
        print(f"  - {item['quantity']}{unit} {item['name']}")


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "message",
        nargs="?",
        default=DEFAULT_REQUEST,
        help="User request for the agent.",
    )
    args = parser.parse_args()

    agent = RecipeShoppingListAgent()
    out = agent.handle_request(args.message)

    print(f"Request: {args.message}\n")

    if out["refused"]:
        print(f"Refused: {out['message']}")
        return

    artifact = out.get("accepted_artifact")
    if artifact is None:
        print(
            f"No recipe accepted after {agent.config.max_attempts} attempt(s) "
            f"(stop_reason={out.get('stop_reason')}).",
        )
        return

    _print_recipe_and_shopping_list(artifact)


if __name__ == "__main__":
    main()
