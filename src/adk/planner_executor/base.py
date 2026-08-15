class PlannerExecutorBase(Runnable[dict[str, Any], dict[str, Any]]):
    """Template for LangGraph-backed planner-executor agents.

    **Invoke input:** ``task`` (str), ``context`` (dict), optional ``session_label`` and
    ``max_iterations``. Optional ``RunnableConfig`` forwards tags, metadata, callbacks, and
    ``run_id`` into the compiled graph.

    **Hub prompts:** When ``prompt_source`` and ``langsmith_client`` are both supplied, system
    prompts are pulled once via :func:`~prompt_hub.prompts_for_config` and stamped on each invoke
    as ``prompt_manifest`` in trace metadata.

    **Offline construction:** Passing ``prompt_source=None`` **and** ``langsmith_client=None`` skips
    the Hub pull entirely; ``_planner_system`` / ``_drafter_system`` become ``""`` and the manifest
    becomes ``{}`` (or a caller-supplied ``prompt_manifest``). Intended for subclasses that fully
    inject planner/executors (so the system prompts are unused) - e.g. deterministic skeletons or
    hermetic tests. Supplying exactly one of the two raises ``TypeError``.

    **Invoke output:** final graph state plus ``invoke_trace`` containing
    ``langsmith_run_id``, ``langsmith_message_id`` (best-effort), and ``variant``.
    Use :meth:`invoke_trace_metadata` for eval-harness-compatible metadata keys.
    Use :meth:`to_eval_run_result` to build a :class:`~adk.eval_harness.cases.RunResult`
    row from invoke output.

    Subclasses supply :attr:`variant`, :meth:`_input_to_state`, and :meth:`_build_graph`.
    Topology-specific loops live in subclass graph builders only. Graph nodes resolve tools via
    :meth:`~PlannerExecutorConfig.tools_for_node` (not a single agent-wide allowlist).
    """

    def __init__(
        self,
        *,
        config: PlannerExecutorConfig | None = None,
        prompt_source: PromptSourceConfig | None = None,
        langsmith_client: Any | None = None,
        prompt_manifest: PromptManifest | None = None,
    ) -> None:
        super().__init__()
        self.config = config or PlannerExecutorConfig()
        if prompt_source is None and langsmith_client is None:
            logger.warning(
                "Offline construction: skipping LangSmith Hub prompt pull "
                "(prompt_source and langsmith_client are both None); planner/executors "
                "must be fully injected and hub system prompts are empty.",
            )
            self._planner_system = ""
            self._drafter_system = ""
            self._prompt_manifest = dict(prompt_manifest) if prompt_manifest else {}
        else:
            if langsmith_client is None:
                msg = "langsmith_client is required for LangSmith Hub prompt loading"
                raise TypeError(msg)
            if prompt_source is None:
                msg = "prompt_source is required for LangSmith Hub prompt loading"
                raise TypeError(msg)
            loaded = prompts_for_config(langsmith_client, prompt_source)
            self._planner_system = loaded.planner_system_prompt
            self._drafter_system = loaded.drafter_system_prompt
            self._prompt_manifest = loaded.manifest
        self.graph = self._build_graph()

    @property
    @abstractmethod
    def variant(self) -> PlannerExecutorVariant:
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

    @classmethod
    def invoke_trace_metadata(cls, out: dict[str, Any]) -> dict[str, Any]:
        """Return LangSmith correlation fields from ``out`` for ``RunResult.metadata``."""
        trace = out.get(INVOKE_TRACE_KEY)
        if not isinstance(trace, dict):
            return {}
        return {
            key: trace[key]
            for key in _INVOKE_TRACE_METADATA_KEYS
            if key in trace
        }

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
        run_id = metadata.get(LANGSMITH_RUN_ID_KEY)
        return RunResult(
            case_id=case_id,
            run_id=run_id,
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
        logger.info("Starting planner-executor graph (invoke) variant=%s", self.variant.value)
        state = self._input_to_state(input)
        invoke_config, collector = prepare_invoke_config(
            self.variant,
            input,
            config,
            prompt_manifest=self._prompt_manifest,
        )
        out = dict(self.graph.invoke(state, invoke_config, **kwargs))
        wait_for_all_tracers()
        logger.info("Planner-executor graph execution complete (invoke)")
        run_id = invoke_config.get("run_id")
        trace = build_invoke_trace(
            collector.traced_runs,
            variant=self.variant,
            run_id_fallback=str(run_id) if run_id is not None else None,
            session_label=_session_label_from_input(input),
            prompt_manifest=self._prompt_manifest,
        )
        return attach_invoke_trace(out, trace)

    @override
    def stream(
        self,
        input: dict[str, Any],
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> Iterator[dict[str, Any]]:
        logger.info("Starting planner-executor graph (stream) variant=%s", self.variant.value)
        state = self._input_to_state(input)
        invoke_config, collector = prepare_invoke_config(
            self.variant,
            input,
            config,
            prompt_manifest=self._prompt_manifest,
        )
        last: dict[str, Any] | None = None
        for update in self.graph.stream(state, invoke_config, stream_mode="values", **kwargs):
            if last is not None:
                yield last
            last = dict(update)
        wait_for_all_tracers()
        logger.info("Planner-executor graph execution complete (stream)")
        if last is None:
            return
        run_id = invoke_config.get("run_id")
        trace = build_invoke_trace(
            collector.traced_runs,
            variant=self.variant,
            run_id_fallback=str(run_id) if run_id is not None else None,
            session_label=_session_label_from_input(input),
            prompt_manifest=self._prompt_manifest,
        )
        yield attach_invoke_trace(last, trace)

    def get_graph(self) -> Any:
        """Expose the compiled graph for visualization or advanced debugging."""
        return self.graph


def _session_label_from_input(input: dict[str, Any]) -> str | None:
    session_label = input.get("session_label")
    if isinstance(session_label, str) and session_label:
        return session_label
    return None
