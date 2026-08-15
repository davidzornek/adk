"""Template for LangGraph-backed planner-executor agents.

**Invoke input:** ``task`` (str), ``context`` (dict), optional ``session_label`` and
``max_iterations``. Optional ``RunnableConfig`` forwards tags, metadata, callbacks, and
``run_id`` into the compiled graph.

**Prompts:** System prompts are plain strings/constants owned by the subclass (or the
``Runnable``s it injects, e.g. :class:`~adk.anthropic_runnables.AnthropicRunnable`) - no
Hub pull. An optional ``prompt_manifest`` records which prompt versions were used, surfaced
in ``invoke_trace`` for eval/trace metadata.

**Invoke output:** final graph state plus ``invoke_trace``, a dict with ``run_id`` (a fresh
``uuid4()`` per call), ``variant``, ``session_label``, and ``prompt_manifest``.
Use :meth:`invoke_trace_metadata` for eval-harness-compatible metadata keys.
Use :meth:`to_eval_run_result` to build a :class:`~adk.eval_harness.cases.RunResult`
row from invoke output.

Subclasses supply :attr:`variant`, :meth:`_input_to_state`, and :meth:`_build_graph`.
Topology-specific loops live in subclass graph builders only. Graph nodes resolve tools via
:meth:`~PlannerExecutorConfig.tools_for_node` (not a single agent-wide allowlist).
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from langchain_core.runnables import Runnable
from langchain_core.runnables.config import RunnableConfig
from typing_extensions import override

from .config import PlannerExecutorConfig

if TYPE_CHECKING:
    # eval_harness.cases doesn't exist until #9 lands; drop the ignore once it does.
    from adk.eval_harness.cases import RunResult  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)

INVOKE_TRACE_KEY = "invoke_trace"


class PlannerExecutorBase(Runnable[dict[str, Any], dict[str, Any]]):
    """Template for LangGraph-backed planner-executor agents.

    **Invoke input:** ``task`` (str), ``context`` (dict), optional ``session_label`` and
    ``max_iterations``. Optional ``RunnableConfig`` forwards tags, metadata, callbacks, and
    ``run_id`` into the compiled graph.

    **Prompts:** System prompts are plain strings/constants owned by the subclass (or the
    ``Runnable``s it injects, e.g. :class:`~adk.anthropic_runnables.AnthropicRunnable`) - no
    Hub pull. An optional ``prompt_manifest`` records which prompt versions were used,
    surfaced in ``invoke_trace`` for eval/trace metadata.

    **Invoke output:** final graph state plus ``invoke_trace``, a dict with ``run_id`` (a
    fresh ``uuid4()`` per call), ``variant``, ``session_label``, and ``prompt_manifest``.
    Use :meth:`invoke_trace_metadata` for eval-harness-compatible metadata keys.
    Use :meth:`to_eval_run_result` to build a :class:`~adk.eval_harness.cases.RunResult`
    row from invoke output.

    Subclasses supply :attr:`variant`, :meth:`_input_to_state`, and :meth:`_build_graph`.
    Topology-specific loops live in subclass graph builders only. Graph nodes resolve tools
    via :meth:`~PlannerExecutorConfig.tools_for_node` (not a single agent-wide allowlist).
    """

    def __init__(
        self,
        *,
        config: PlannerExecutorConfig | None = None,
        prompt_manifest: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self.config = config or PlannerExecutorConfig()
        self._prompt_manifest = dict(prompt_manifest) if prompt_manifest else {}
        self.graph = self._build_graph()

    @property
    @abstractmethod
    def variant(self) -> str:
        """Stable pattern id for callers and downstream stratification."""

    @abstractmethod
    def _input_to_state(self, input: dict[str, Any]) -> dict[str, Any]:
        """Map caller input to initial graph state."""

    @abstractmethod
    def _build_graph(self) -> Any:
        """Compile and return the LangGraph (or compatible) workflow."""

    def eval_harness_graph_node_ids(self) -> tuple[str, ...]:
        """Logical graph node ids for eval harness scoring (derived from the compiled graph)."""
        from .graph import logical_graph_node_ids

        return logical_graph_node_ids(self.graph)

    def _build_invoke_trace(self, input: dict[str, Any], run_id: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "variant": self.variant,
            "session_label": _session_label_from_input(input),
            "prompt_manifest": self._prompt_manifest,
        }

    @classmethod
    def invoke_trace_metadata(cls, out: dict[str, Any]) -> dict[str, Any]:
        """Return the ``invoke_trace`` dict from ``out``, for ``RunResult.metadata``."""
        trace = out.get(INVOKE_TRACE_KEY)
        return trace if isinstance(trace, dict) else {}

    @classmethod
    def to_eval_run_result(
        cls,
        out: dict[str, Any],
        *,
        case_id: str,
        output: str | dict[str, Any] | list[Any] | None = None,
    ) -> RunResult:
        """Build a :class:`~adk.eval_harness.cases.RunResult` from invoke output."""
        from adk.eval_harness.cases import RunResult

        metadata = cls.invoke_trace_metadata(out)
        return RunResult(
            case_id=case_id,
            run_id=metadata.get("run_id"),
            output=output,
            metadata=metadata,
        )

    @override
    def invoke(
        self,
        input: dict[str, Any],
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        logger.info("Starting planner-executor graph (invoke) variant=%s", self.variant)
        state = self._input_to_state(input)
        run_id = str(uuid4())
        out = dict(self.graph.invoke(state, config, **kwargs))
        logger.info("Planner-executor graph execution complete (invoke)")
        out[INVOKE_TRACE_KEY] = self._build_invoke_trace(input, run_id)
        return out

    @override
    def stream(
        self,
        input: dict[str, Any],
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> Iterator[dict[str, Any]]:
        logger.info("Starting planner-executor graph (stream) variant=%s", self.variant)
        state = self._input_to_state(input)
        run_id = str(uuid4())
        last: dict[str, Any] | None = None
        for update in self.graph.stream(state, config, stream_mode="values", **kwargs):
            if last is not None:
                yield last
            last = dict(update)
        logger.info("Planner-executor graph execution complete (stream)")
        if last is None:
            return
        last[INVOKE_TRACE_KEY] = self._build_invoke_trace(input, run_id)
        yield last

    def get_compiled_graph(self) -> Any:
        """Expose the compiled LangGraph workflow for visualization or advanced debugging.

        Named to avoid shadowing :meth:`Runnable.get_graph`, which returns an unrelated
        LangChain-composition ``Graph`` for a different (incompatible) purpose.
        """
        return self.graph


def _session_label_from_input(input: dict[str, Any]) -> str | None:
    session_label = input.get("session_label")
    if isinstance(session_label, str) and session_label:
        return session_label
    return None
