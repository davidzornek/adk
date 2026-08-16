"""Template for LangGraph-backed generate-evaluate-reflect agents.

Mirrors :class:`~adk.planner_executor.base.PlannerExecutorBase`'s split for the GER pattern:
subclasses own prompts, tool schemas, and the ``generator``/``evaluator``/``reflector``
``Runnable``s that use them; this base class owns graph construction and a uniform
``invoke()``. See ``docs/4_generate_evaluate_reflect_agent_components.md`` for the pattern's
logical schema.

**Invoke input:** whatever :meth:`_input_to_state` maps into GER state - see
:class:`~adk.generate_evaluate_reflect.state.GenerateEvaluateReflectState` for the full shape,
but subclasses typically only need ``task`` (str) and ``context`` (dict) from the caller. If
the mapped state omits ``max_attempts``, it defaults to ``self.config.max_attempts``.

**Invoke output:** the final graph state - ``candidate``, ``eval_verdict``/``eval_rationale``,
``attempts``, ``accepted_artifact``, ``stop_reason``.

Subclasses supply :attr:`variant`, :meth:`_build_generator`, :meth:`_build_evaluator`,
:meth:`_build_reflector`, and :meth:`_input_to_state`.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from langchain_core.runnables import Runnable
from langchain_core.runnables.config import RunnableConfig
from typing_extensions import override

from .config import GenerateEvaluateReflectConfig
from .graph import build_ger_closed_loop_graph


class GenerateEvaluateReflectBase(Runnable[dict[str, Any], dict[str, Any]]):
    """Template for LangGraph-backed generate-evaluate-reflect agents."""

    def __init__(self, *, config: GenerateEvaluateReflectConfig | None = None) -> None:
        super().__init__()
        self.config = config or GenerateEvaluateReflectConfig()
        self.graph = build_ger_closed_loop_graph(
            generator=self._build_generator(),
            evaluator=self._build_evaluator(),
            reflector=self._build_reflector(),
        )

    @property
    @abstractmethod
    def variant(self) -> str:
        """Stable pattern id for callers and downstream stratification."""

    @abstractmethod
    def _build_generator(self) -> Runnable[dict[str, Any], dict[str, Any]]:
        """Build the generator Runnable: proposes a ``candidate`` from state."""

    @abstractmethod
    def _build_evaluator(self) -> Runnable[dict[str, Any], dict[str, Any]]:
        """Build the evaluator Runnable: returns ``eval_verdict``/``eval_rationale``."""

    @abstractmethod
    def _build_reflector(self) -> Runnable[dict[str, Any], dict[str, Any]]:
        """Build the reflector Runnable: turns a rejected attempt into ``reflection_feedback``."""

    @abstractmethod
    def _input_to_state(self, input: dict[str, Any]) -> dict[str, Any]:
        """Map caller input to initial graph state."""

    @override
    def invoke(
        self,
        input: dict[str, Any],
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        state = self._input_to_state(input)
        state.setdefault("max_attempts", self.config.max_attempts)
        return dict(self.graph.invoke(state, config, **kwargs))

    def get_compiled_graph(self) -> Any:
        """Expose the compiled LangGraph workflow for visualization or advanced debugging.

        Named to avoid shadowing :meth:`Runnable.get_graph`, which returns an unrelated
        LangChain-composition ``Graph`` for a different (incompatible) purpose.
        """
        return self.graph
