"""Single-LLM evaluation harness: LangSmith runs, scoring, and batch rollups.

Wires dataset rows (:class:`~eval_harness.cases.EvalCase`) and model outputs
(:class:`~eval_harness.cases.RunResult`) into named metrics (built-ins or callables you
register). Classmethods load completed runs from LangSmith, or run agent eval via
:meth:`run_agent_eval` / :meth:`arun_agent_eval` (LangSmith ``evaluate`` / ``aevaluate`` ->
:meth:`from_experiment` -> :meth:`score_batch`). Pass ``score=True`` to those two methods to run
``score_batch`` inline and read the rollups off the returned harness's ``scores`` attribute.

``MetricFn`` is the type of a registered custom metric: ``(EvalCase, RunResult) ->`` a mapping or
Pydantic :class:`~pydantic.BaseModel` (no ``*args`` / ``**kwargs``).
"""

from __future__ import annotations

import asyncio
import datetime
import inspect
import logging
import random
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, Type

from langsmith import Client
from langsmith import run_helpers as langsmith_run_helpers
from langsmith.schemas import Example
from pydantic import BaseModel

from llm_utils.eval_harness._score_rollups import rollup_score_blocks
from llm_utils.eval_harness.builtins import builtin_metric_handlers
from llm_utils.eval_harness.cases import EvalCase, RunResult
from llm_utils.eval_harness.constants import (
    DEFAULT_CRITERION_SCORE_KEYS,
    DEFAULT_PHASE1_METRICS,
    METRIC_CLASSIFICATION,
    METRIC_DISTRIBUTIONAL,
    METRIC_GOLDEN_SET,
    METRIC_OPERATIONAL,
    METRIC_STRUCTURED_OUTPUT,
)
from llm_utils.eval_harness.langsmith_mapping import (
    eval_case_from_langsmith_example,
    pair_from_langsmith_run,
    run_result_for_experiment_run,
)
from llm_utils.eval_harness.agent_eval.evaluators import (
    filter_evaluators_by_feedback,
    resolve_evaluators,
)
from llm_utils.eval_harness.agent_eval.replay import (
    _build_replay_target_from_pairs,
    _examples_for_replay,
    _feedback_by_run_from_pairs,
)
from llm_utils.eval_harness.agent_eval.types import AgentEvalRun, EvaluatorSpec
from llm_utils.eval_harness.output_models import (
    MetricScoreBlock,
    ScoreBatchOutput,
    pair_row_identifier_fields,
)
from llm_utils.eval_harness.reporting import rollup_run_results

logger = logging.getLogger(__name__)

# Post-evaluate reload (#57): client.flush() forces the SDK's run upload, but LangSmith's read
# side can still lag, so `from_experiment` may briefly load zero pairs. Poll a bounded number of
# times before giving up.
_RELOAD_RETRY_ATTEMPTS = 8
_RELOAD_RETRY_DELAY_S = 0.5

# Custom scorers must look like built-ins: two positional args, no *args/**kwargs.
MetricFn = Callable[[EvalCase, RunResult], Mapping[str, Any] | BaseModel]


def _normalize_metric_return(raw: Mapping[str, Any] | BaseModel) -> dict[str, Any]:
    """Coerce a metric callable return value to a plain dict for wrapping."""
    if isinstance(raw, BaseModel):
        return raw.model_dump()
    return dict(raw)


# Keys hoisted to ``result`` (primary outcome) vs ``metadata`` (supporting detail) per built-in.
_RESULT_KEYS_BY_METRIC: dict[str, tuple[str, ...]] = {
    METRIC_STRUCTURED_OUTPUT: ("parse_ok", "schema_valid"),
    METRIC_DISTRIBUTIONAL: ("output_char_length", "output_is_empty", "finish_reason"),
    METRIC_OPERATIONAL: (
        "latency_ms",
        "tokens_in",
        "tokens_out",
        "tokens_total",
        "cost_usd",
        "completion_tokens_per_s",
        "total_tokens_per_s",
    ),
    METRIC_GOLDEN_SET: (
        "applicable",
        "text_exact_match",
        "text_normalized_match",
        "json_match",
        "dict_match",
    ),
    METRIC_CLASSIFICATION: ("applicable", "by_head"),
}


def _wrap_score_block(requested_name: str, inner: dict[str, Any]) -> dict[str, Any]:
    """Normalize one metric to ``{metric, result, metadata}`` for ``score_one`` / ``per_pair``."""
    if "error" in inner:
        return {
            "metric": requested_name,
            "result": None,
            "metadata": {"error": inner["error"]},
        }
    body = dict(inner)
    metric_id = body.pop("metric", requested_name)
    keys = _RESULT_KEYS_BY_METRIC.get(metric_id)
    if keys is not None:
        result = {k: body[k] for k in keys if k in body}
        metadata = {k: v for k, v in body.items() if k not in result}
        return {"metric": metric_id, "result": result, "metadata": metadata}
    # Custom metrics: optional explicit ``result`` key is promoted; rest stays in metadata.
    if "result" in body:
        body = dict(body)
        explicit = body.pop("result")
        return {"metric": metric_id, "result": explicit, "metadata": body}
    return {"metric": metric_id, "result": None, "metadata": body}


def _validate_metric_fn(fn: Callable[..., Any]) -> None:
    """Ensure ``fn`` looks like ``(case, result) -> mapping`` with no ``*args`` / ``**kwargs``.

    Raises:
        TypeError: If the signature does not match harness expectations.
    """
    sig = inspect.signature(fn)
    if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values()):
        raise TypeError("Custom metric must not use *args")
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        raise TypeError("Custom metric must not use **kwargs")
    params = list(sig.parameters.values())
    if len(params) != 2:
        raise TypeError(f"Custom metric must accept exactly (case, result); got {len(params)} parameters")
    for p in params:
        if p.default is inspect.Parameter.empty and p.kind not in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            raise TypeError("Custom metric parameters must be positional or keyword")


def _append_list_feedback_batched_by_run(
    client: Any,
    buckets: dict[str, list[dict[str, Any]]],
    run_ids: Sequence[str],
    *,
    batch_size: int = 20,
) -> None:
    """Fill ``buckets`` (run id -> feedback row dicts) via ``client.list_feedback`` in fixed-size batches."""
    for i in range(0, len(run_ids), batch_size):
        hi = i + batch_size
        batch = list(run_ids[i:hi])
        fb_iter = client.list_feedback(run_ids=batch)
        if fb_iter is None:
            continue
        for fb in fb_iter:
            if fb.run_id is None:
                continue
            rid = str(fb.run_id)
            if rid not in buckets:
                continue
            row: dict[str, Any] = {"key": fb.key, "score": fb.score, "value": fb.value}
            if fb.comment is not None:
                row["comment"] = fb.comment
            buckets[rid].append(row)


class SingleLLMEvalHarness:
    """Score one or many completed LLM runs using a **required** metric list plus optional extras.

    **What this is for**

    After your code has run the model and built a ``RunResult`` (text/JSON output, optional
    latency, tokens, etc.), you pass ``(EvalCase, RunResult)`` here to get **per-metric dicts** - for
    example whether the output parsed as JSON, output length, or (if enabled) match against
    ``EvalCase.expected_*``.

    **Built-in metric names** (see ``eval_harness.constants``)

    - ``structured_output`` - JSON parse + optional Pydantic schema check.
    - ``distributional`` - output length, empty flag, ``finish_reason``.
    - ``operational`` - latency, token counts, throughput (tokens/s), optional USD cost from
      ``RunResult`` / usage, or ``read_run`` when you pass ``langsmith_client`` (LangSmith SoT).
    - ``classification`` - per-head sklearn-style metrics (``classes``, ``per_class``, ``global``
      micro/macro/weighted, ``accuracy``, ``n_rows``) when ``EvalCase.classification_ground_truth``
      and ``RunResult.classification_prediction`` supply intersecting head keys. Batch rollups nest
      under each head in ``rollup["metrics"]``.
    - ``golden_set`` - runs when included in ``required_metrics`` (for example add
      ``METRIC_GOLDEN_SET``); compares to expected fields on the case.
    - ``criteria_scores`` - opt-in; reads LLM-judge scores obtained from LangSmith when they are
      copied onto ``RunResult.metadata`` (typically the LangSmith ``feedback`` list and/or a
      ``criteria_scores`` dict). Keys default to ``DEFAULT_CRITERION_SCORE_KEYS``; override via
      ``criteria_score_keys`` on the harness.

    **Custom metrics**

    Use ``register_metric("my_metric", fn)`` where ``fn(case, result)`` returns a dict (or
    Pydantic model). Include a ``"result"`` key in that dict to surface your primary value next to
    ``metric``; other keys become ``metadata``. Pass extra names in ``score_one`` / ``score_batch``
    ``metrics=`` to run them **in addition to** the required metrics (duplicates are ignored). There
    is **no** automatic batch rollup for custom keys unless you add your own aggregation over
    ``per_pair``.

    **``score_one`` return shape**

    Keys are metric names. Each value is::

        {"metric": "<id>", "result": <dict | any | None>, "metadata": {...}}

    **Built-ins:** ``result`` holds the main measurements (e.g. ``parse_ok``, ``schema_valid`` for
    structured output; length / empty / ``finish_reason`` for distributional; match flags for
    golden). **Supporting** fields (``computed``, ``parse_error``, ``schema_error``, ...) stay in
    ``metadata``.

    **Custom metrics:** return a dict; if you include a top-level ``"result"`` key, that value is
    promoted to ``result`` and all other keys (except ``"metric"``) go to ``metadata``. If you omit
    ``result``, it is ``None`` and the full return body (minus ``metric``) is in ``metadata``.

    **Failures** (``fail_fast=False``): ``result`` is ``None`` and ``metadata`` contains ``error``.

    **Batch output shape** (``score_batch``)

    - ``n_pairs`` - how many ``(case, result)`` tuples you passed.
    - ``per_pair`` - one dict per pair: ``case_id``, ``dataset_id``, and ``run_id`` (from
      :class:`~eval_harness.cases.EvalCase` / :class:`~eval_harness.cases.RunResult`) plus the same
      metric blocks ``score_one`` would return. Omit with ``include_per_pair=False`` to save space.
    - ``rollup`` - two blocks:
        1. ``rollup["operational"]`` - telemetry rollups from ``RunResult`` only (latency quantiles,
           token totals, throughput, cost, coarse output stats). Same shape regardless of which
           scoring metrics ran; adding a scorer does not require new rollup code in ``reporting``.
        2. ``rollup["metrics"]`` - aggregates from each metric's ``result`` **merged with**
           ``metadata`` (same keys rollups used before ``result`` existed). Keys mirror every metric
           that ran (required plus any extras from ``metrics=``).
    """

    def __init__(
        self,
        *,
        structured_output_model: Type[BaseModel] | None = None,
        required_metrics: Sequence[str] = DEFAULT_PHASE1_METRICS,
        criteria_score_keys: Sequence[str] | None = None,
        langsmith_client: Any | None = None,
    ) -> None:
        """Configure required metrics and optional schema for structured-output checks.

        Args:
            structured_output_model: If set, the ``structured_output`` built-in also checks that
                parsed JSON validates against this Pydantic model (in addition to parse success).
            required_metrics: Ordered list of metric **names** that **always** run on every
                ``score_one`` / ``score_batch``. Defaults to :data:`~eval_harness.constants.DEFAULT_PHASE1_METRICS`.
            criteria_score_keys: Which criterion names the ``criteria_scores`` built-in reports.
                Defaults to ``DEFAULT_CRITERION_SCORE_KEYS`` (default LangSmith LLM-judge keys for
                this harness).
            langsmith_client: Optional ``langsmith.Client`` for ``operational`` cost when
                ``RunResult.cost_usd`` is unset; ``read_run`` using ``metadata`` ``langsmith_run_id``
                or ``langsmith_message_id`` (if your runner copies trace ids into metadata).
                Stakeholder spend should come from LangSmith, not catalog estimates.
        """
        self._structured_model = structured_output_model
        self._langsmith_client = langsmith_client
        self._criteria_score_keys: tuple[str, ...] = (
            tuple(criteria_score_keys)
            if criteria_score_keys is not None
            else DEFAULT_CRITERION_SCORE_KEYS
        )
        self._required_metrics = tuple(required_metrics)
        self._custom: dict[str, MetricFn] = {}
        self._builtin_handlers: dict[str, MetricFn] = builtin_metric_handlers(
            structured_model=self._structured_model,
            langsmith_client=self._langsmith_client,
            criteria_score_keys=self._criteria_score_keys,
        )
        self._pairs: tuple[tuple[EvalCase, RunResult], ...] | None = None
        self._agent_eval_run: AgentEvalRun | None = None
        self._score_batch_output: dict[str, Any] | None = None

    @property
    def scores(self) -> dict[str, Any] | None:
        """``score_batch`` output when :meth:`run_agent_eval` / :meth:`arun_agent_eval` ran with ``score=True``.

        ``None`` for harnesses built without inline scoring (``score=False``, the default) or when
        the post-eval reload produced no pairs. The dict shape matches :meth:`score_batch` (see
        :class:`~eval_harness.output_models.ScoreBatchOutput`).
        """
        return self._score_batch_output

    @property
    def agent_eval_run(self) -> AgentEvalRun | None:
        """LangSmith run metadata when this harness was built via :meth:`run_agent_eval` or :meth:`arun_agent_eval`.

        ``None`` for harnesses created only through :meth:`from_pairs`, :meth:`from_traces`, or
        :meth:`from_experiment` (without the agent-eval run phase).
        """
        return self._agent_eval_run

    @property
    def pairs(self) -> tuple[tuple[EvalCase, RunResult], ...]:
        """Deep-copied ``(EvalCase, RunResult)`` rows from :meth:`from_pairs` or trace loaders."""
        if self._pairs is None:
            raise ValueError("No pairs have been loaded; use from_pairs or pass pairs= to score_batch.")
        return self._pairs

    @classmethod
    def from_pairs(
        cls,
        pairs: Sequence[tuple[EvalCase, RunResult]],
        *,
        structured_output_model: Type[BaseModel] | None = None,
        required_metrics: Sequence[str] = DEFAULT_PHASE1_METRICS,
        criteria_score_keys: Sequence[str] | None = None,
        langsmith_client: Any | None = None,
    ) -> SingleLLMEvalHarness:
        """Build a harness from in-memory rows; stores a deep copy for :attr:`pairs` / :meth:`score_batch`."""
        inst = cls(
            structured_output_model=structured_output_model,
            required_metrics=required_metrics,
            criteria_score_keys=criteria_score_keys,
            langsmith_client=langsmith_client,
        )
        inst._pairs = tuple((c.model_copy(deep=True), r.model_copy(deep=True)) for c, r in pairs)
        return inst

    @classmethod
    def from_traces(
        cls,
        client: Any,
        *,
        project_name: str | None = None,
        project_id: str | None = None,
        n: int,
        seed: int | None = 0,
        limit: int | None = 2500,
        sample_order: Literal["random", "recent"] = "random",
        **harness_kw: Any,
    ) -> SingleLLMEvalHarness:
        """Load up to ``n`` root runs from LangSmith (``list_runs`` -> ``read_run`` + ``list_feedback``).

        Each sampled run is mapped with :func:`~eval_harness.langsmith_mapping.pair_from_langsmith_run`
        (including ``list_feedback`` rows). The harness is then built via :meth:`from_pairs`.

        Args:
            client: LangSmith client with ``list_runs``, ``read_run``, and ``list_feedback`` (e.g.
                ``langsmith.Client``).
            project_name: Passed to ``list_runs(project_name=...)``. Exactly one of
                ``project_name`` or ``project_id`` is required.
            project_id: Passed to ``list_runs(project_id=...)``. Exactly one of ``project_name`` or
                ``project_id`` is required.
            n: Target number of runs to score after sampling; uses ``k = min(max(n, 0), len(rows))``
                on the ``list_runs`` result.
            seed: RNG seed for ``random.Random(seed).sample`` when ``sample_order`` is ``"random"``;
                ``None`` is treated as ``0``. Ignored when ``sample_order`` is ``"recent"``.
            limit: Passed to ``list_runs(limit=...)`` to cap how many runs are listed before sampling
                (default ``2500``). Pass ``None`` to omit ``limit`` and use the LangSmith client default.
            sample_order: ``"random"`` (default) samples ``k`` rows with ``seed``; ``"recent"`` takes the
                ``k`` root runs with latest ``start_time`` after sorting the listed rows.
            structured_output_model: Forwarded to :meth:`from_pairs` / ``__init__``.
            required_metrics: Forwarded to :meth:`from_pairs` / ``__init__`` (defaults to
                :data:`~eval_harness.constants.DEFAULT_PHASE1_METRICS`).
            criteria_score_keys: Forwarded to :meth:`from_pairs` / ``__init__``.
            langsmith_client: Forwarded to :meth:`from_pairs` / ``__init__`` (often the same object
                as ``client`` for operational ``read_run`` cost during scoring).

        ``list_runs`` is always called with ``is_root=True``.
        """
        if (project_name is None) == (project_id is None):
            raise ValueError("Pass exactly one of project_name or project_id.")
        lr_kw: dict[str, Any] = {"is_root": True}
        if project_name is not None:
            lr_kw["project_name"] = project_name
        else:
            lr_kw["project_id"] = project_id
        if limit is not None:
            lr_kw["limit"] = limit
        rows = list(client.list_runs(**lr_kw))
        k = min(max(n, 0), len(rows))
        if sample_order == "recent":
            rows.sort(key=lambda run: str(getattr(run, "start_time", "") or ""))
            picked = rows[-k:] if k else []
        else:
            rng = random.Random(0 if seed is None else seed)
            picked = rng.sample(rows, k=k) if k else []
        built: list[tuple[EvalCase, RunResult]] = []
        for row in picked:
            rid_s = str(row.id)
            full = client.read_run(rid_s)
            fb_iter = client.list_feedback(run_ids=[rid_s])
            fb_list = list(fb_iter) if fb_iter is not None else []
            built.append(pair_from_langsmith_run(full, feedback_entries=fb_list))
        return cls.from_pairs(built, **harness_kw)

    # TODO: fix once classification prediction input layout is standardized.
    # Classification: ``RunResult.classification_prediction`` is filled from ``*_pred`` keys on
    # run's ``inputs`` dict - a placeholder for one experiment layout where predictions live on
    # inputs. That is not the right long-term shape; a future ticket will fix it. This hack exists
    # only to unblock harness scoring for that layout.
    @classmethod
    def from_experiment(
        cls,
        client: Any,
        *,
        experiment_name: str,
        limit: int | None = 2500,
        **harness_kw: Any,
    ) -> SingleLLMEvalHarness:
        """Load scored pairs from a LangSmith **experiment** (tracer session) project.

        Follows the dataset-example + reference-run path: ``read_project`` -> ``list_examples``
        (using the project's ``reference_dataset_id``) -> ``list_runs`` (match
        ``reference_example_id``) -> batched ``list_feedback``.

        Returns one ``(EvalCase, RunResult)`` per listed example that has a matching reference run,
        in **example list order** (no subsampling).

        Args:
            client: LangSmith client with ``read_project``, ``list_examples``, ``list_runs``, and
                ``list_feedback``.
            experiment_name: LangSmith **project name** for the experiment (same string used in
                the UI / ``read_project(project_name=...)``).
            limit: Passed to ``list_examples(limit=...)`` (default ``2500``). Pass ``None`` to omit
                ``limit`` and use the LangSmith client default.
            Remaining keyword arguments: forwarded to :meth:`from_pairs` / ``__init__``.
        """
        project = client.read_project(project_name=experiment_name)
        ds_id = getattr(project, "reference_dataset_id", None)
        if ds_id is None:
            raise ValueError("Experiment project has no reference_dataset_id (cannot load examples).")

        le_kw: dict[str, Any] = {"dataset_id": str(ds_id)}
        if limit is not None:
            le_kw["limit"] = limit
        examples = list(client.list_examples(**le_kw))
        ex_ids = {str(ex.id) for ex in examples}
        runs_by_ex = {}
        for run in client.list_runs(project_name=experiment_name):
            ref_raw = run.reference_example_id
            if ref_raw is None:
                continue
            ref = str(ref_raw)
            if ref in ex_ids and ref not in runs_by_ex:
                runs_by_ex[ref] = run
            if len(runs_by_ex) >= len(examples):
                break

        run_ids = [str(r.id) for r in runs_by_ex.values()]
        feedback_by_run: dict[str, list[dict[str, Any]]] = {rid: [] for rid in run_ids}
        _append_list_feedback_batched_by_run(client, feedback_by_run, run_ids)

        built_pairs: list[tuple[EvalCase, RunResult]] = []
        for ex in examples:
            run = runs_by_ex.get(str(ex.id))
            if run is None:
                continue
            rid = str(run.id)
            case = eval_case_from_langsmith_example(ex, dataset_id=str(ds_id))
            res = run_result_for_experiment_run(case, run, feedback_by_run.get(rid, []))
            built_pairs.append((case, res))

        return cls.from_pairs(built_pairs, **harness_kw)

    @staticmethod
    def _agent_eval_prefix(experiment_prefix: str | None) -> str:
        if experiment_prefix is not None:
            return experiment_prefix
        return datetime.datetime.now().strftime("agent-eval-%Y%m%d-%H%M%S")

    @staticmethod
    def _dataset_data_name(dataset: str) -> str:
        if "/" not in dataset:
            return dataset
        workspace_name, bare_name = dataset.split("/", 1)
        if not workspace_name or not bare_name:
            raise ValueError(f"Both workspace and name must be non-empty, got: {dataset!r}")
        return bare_name

    @staticmethod
    def _limit_eval_data(
        data: str | list[Example],
        client: Any,
        limit: int | None,
    ) -> str | list[Example]:
        if limit is None:
            return data
        if isinstance(data, list):
            return data[:limit]
        examples = list(client.list_examples(dataset_name=data, limit=limit))
        logger.info("Limited to %d examples", len(examples))
        return examples

    @staticmethod
    def _session_id_from_results(results: Any) -> str | None:
        try:
            experiment = results._manager._experiment
        except AttributeError:
            return None
        if experiment is None:
            return None
        return str(experiment.id)

    @staticmethod
    def _sync_result_row_count(results: Any) -> int:
        count = 0
        for _ in results:
            count += 1
        return count

    @staticmethod
    async def _async_result_row_count(results: Any) -> int:
        count = 0
        async for _ in results:
            count += 1
        return count

    @staticmethod
    def _langsmith_target_is_async(target: Any) -> bool:
        """True when ``target`` must use LangSmith ``aevaluate`` rather than ``evaluate``."""
        return callable(target) and langsmith_run_helpers.is_async(target)

    @classmethod
    def _run_arun_agent_eval_sync(
        cls,
        *,
        target: Any,
        dataset: str,
        client: Any,
        evaluators: list[EvaluatorSpec] | None,
        experiment_prefix: str | None,
        limit: int | None,
        max_concurrency: int,
        existing_experiment_name: str | None,
        harness_kw: dict[str, Any],
        prompt_manifest: dict[str, dict[str, str]] | None = None,
        score: bool = False,
        score_metrics: Sequence[str] | None = None,
        include_per_pair: bool = True,
        fail_fast: bool = False,
    ) -> SingleLLMEvalHarness:
        """Run :meth:`arun_agent_eval` from sync call sites (no running event loop)."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            async_harness_kw = dict(harness_kw)
            if prompt_manifest is not None:
                async_harness_kw["prompt_manifest"] = prompt_manifest
            return asyncio.run(
                cls.arun_agent_eval(
                    target,
                    dataset=dataset,
                    client=client,
                    evaluators=evaluators,
                    experiment_prefix=experiment_prefix,
                    limit=limit,
                    max_concurrency=max_concurrency,
                    existing_experiment_name=existing_experiment_name,
                    score=score,
                    score_metrics=score_metrics,
                    include_per_pair=include_per_pair,
                    fail_fast=fail_fast,
                )
            )
        raise ValueError(
            "Async target requires an async context. Use "
            "`await SingleLLMEvalHarness.arun_agent_eval(...)` instead of `run_agent_eval`."
        )

    @classmethod
    def _prepare_langsmith_eval(
        cls,
        target: Any,
        *,
        dataset: str,
        client: Any,
        evaluators: list[EvaluatorSpec] | None,
        experiment_prefix: str | None,
        limit: int | None,
        existing_experiment_name: str | None,
        for_aevaluate: bool,
        **harness_kw: Any,
    ) -> tuple[str, str | list[Any], Any, list[Any]]:
        """Build ``evaluate`` / ``aevaluate`` arguments (prefix, data, target, evaluators)."""
        prefix = cls._agent_eval_prefix(experiment_prefix)
        specs = list(evaluators or [])

        replay_pairs = None
        if existing_experiment_name is not None:
            replay_pairs = cls.from_experiment(
                client,
                experiment_name=existing_experiment_name,
                limit=limit,
                **harness_kw,
            ).pairs

        if replay_pairs is not None:
            data = _examples_for_replay(client, replay_pairs)
            target_for_eval = _build_replay_target_from_pairs(replay_pairs)
            feedback_by_run = _feedback_by_run_from_pairs(replay_pairs)
        else:
            data = cls._limit_eval_data(cls._dataset_data_name(dataset), client, limit)
            target_for_eval = target
            feedback_by_run = {}

        resolved = resolve_evaluators(
            filter_evaluators_by_feedback(specs, feedback_by_run),
            for_aevaluate=for_aevaluate,
        )
        return prefix, data, target_for_eval, resolved

    @classmethod
    def _resolve_agent_eval_prompt_manifest(
        cls,
        *,
        explicit: dict[str, dict[str, str]] | None,
        pairs: Sequence[tuple[EvalCase, RunResult]],
    ) -> dict[str, dict[str, str]] | None:
        if explicit:
            return explicit
        for _case, result in pairs:
            manifest = result.metadata.get("prompt_manifest")
            if isinstance(manifest, dict) and manifest:
                return manifest
        return None

    @classmethod
    def _reload_experiment_after_eval(
        cls,
        client: Any,
        *,
        experiment_name: str,
        limit: int | None,
        expected_rows: int,
        harness_kw: dict[str, Any],
    ) -> SingleLLMEvalHarness:
        """Reload the just-created experiment, tolerating LangSmith's post-write lag (#57).

        ``client.flush()`` forces the SDK's background run upload; the read side can still lag, so
        poll ``from_experiment`` until pairs appear (up to :data:`_RELOAD_RETRY_ATTEMPTS`). When the
        run reported no rows there is nothing to wait for, so the first load is returned as-is.
        """
        client.flush()
        inst = cls.from_experiment(
            client, experiment_name=experiment_name, limit=limit, **harness_kw
        )
        if expected_rows <= 0:
            return inst

        attempt = 1
        while not inst.pairs and attempt < _RELOAD_RETRY_ATTEMPTS:
            time.sleep(_RELOAD_RETRY_DELAY_S)
            attempt += 1
            inst = cls.from_experiment(
                client, experiment_name=experiment_name, limit=limit, **harness_kw
            )
        if not inst.pairs:
            logger.warning(
                "Reloaded experiment %r as 0 pairs after %d attempt(s) despite %d reported row(s); "
                "LangSmith may still be indexing.",
                experiment_name,
                attempt,
                expected_rows,
            )
        return inst

    @classmethod
    def _after_langsmith_eval(
        cls,
        client: Any,
        *,
        results: Any,
        prefix: str,
        row_count: int,
        limit: int | None,
        harness_kw: dict[str, Any],
        prompt_manifest: dict[str, dict[str, str]] | None = None,
        score: bool = False,
        score_metrics: Sequence[str] | None = None,
        include_per_pair: bool = True,
        fail_fast: bool = False,
    ) -> SingleLLMEvalHarness:
        experiment_name = str(results.experiment_name)
        session_id = cls._session_id_from_results(results)
        logger.info(
            "Agent eval complete: experiment_name=%r session_id=%r rows=%d",
            experiment_name,
            session_id,
            row_count,
        )
        inst = cls._reload_experiment_after_eval(
            client,
            experiment_name=experiment_name,
            limit=limit,
            expected_rows=row_count,
            harness_kw=harness_kw,
        )
        inst._agent_eval_run = AgentEvalRun(
            experiment_prefix=prefix,
            experiment_name=experiment_name,
            session_id=session_id,
            row_count=row_count,
            prompt_manifest=cls._resolve_agent_eval_prompt_manifest(
                explicit=prompt_manifest,
                pairs=inst.pairs,
            ),
        )
        if score and inst._pairs:
            inst._score_batch_output = inst.score_batch(
                metrics=score_metrics,
                include_per_pair=include_per_pair,
                fail_fast=fail_fast,
            )
        elif score:
            logger.info(
                "score=True but experiment %r reloaded 0 pairs; leaving scores unset.",
                experiment_name,
            )
        return inst

    @classmethod
    def run_agent_eval(
        cls,
        target: Any,
        *,
        dataset: str,
        client: Any | None = None,
        evaluators: Sequence[EvaluatorSpec] | None = None,
        experiment_prefix: str | None = None,
        limit: int | None = None,
        max_concurrency: int = 2,
        existing_experiment_name: str | None = None,
        score: bool = False,
        score_metrics: Sequence[str] | None = None,
        include_per_pair: bool = True,
        fail_fast: bool = False,
        **harness_kw: Any,
    ) -> SingleLLMEvalHarness:
        """Run LangSmith ``evaluate`` on a dataset, load the experiment, and return a scoring harness.

        **Two phases:** (1) LangSmith runs ``target`` x dataset x evaluators and writes traces and
        feedback; (2) this classmethod loads ``(EvalCase, RunResult)`` via :meth:`from_experiment`.
        Call :meth:`score_batch` on the returned instance-same as other loaders.

        Dataset-bound LLM judges (Prompts + evaluators configured on the dataset in the UI) run
        automatically; ``evaluators`` adds optional in-process code judges only.

        Args:
            target: ``langchain_core.runnables.Runnable`` or callable ``(inputs: dict) -> dict``
                (sync or async). Async callables use ``aevaluate`` (via :meth:`arun_agent_eval`
                under the hood); in a running event loop use ``await arun_agent_eval`` directly.
                Ignored when ``existing_experiment_name`` is set (replay uses cached outputs).
            dataset: Dataset name (or ``"workspace/name"``; only the bare name is sent to LangSmith).
                Must live in the workspace implied by your LangSmith env vars.
            client: LangSmith client; defaults to :class:`langsmith.Client` from environment variables.
            evaluators: Optional :class:`~eval_harness.agent_eval.types.CodeEvaluator` or bare
                callables for ``evaluate(..., evaluators=...)``.
            experiment_prefix: Passed to ``client.evaluate``.
            existing_experiment_name: Prior experiment **project name** (same as :meth:`from_experiment`)
                to replay cached outputs and re-run judges without re-invoking ``target``.
            score: When true, also call :meth:`score_batch` on the loaded pairs and expose the
                result via :attr:`scores` (default false preserves the load-only behavior). If the
                reload yields no pairs, :attr:`scores` stays ``None``.
            score_metrics: Extra metric names passed to :meth:`score_batch` as ``metrics=`` (in
                addition to ``required_metrics``); only used when ``score=True``.
            include_per_pair: Forwarded to :meth:`score_batch`; only used when ``score=True``.
            fail_fast: Forwarded to :meth:`score_batch`; only used when ``score=True``.
            harness_kw: Forwarded to :meth:`from_experiment` / ``__init__`` (``required_metrics``,
                ``criteria_score_keys``, ``langsmith_client``, etc.). ``prompt_manifest`` is stored
                on :attr:`~eval_harness.agent_eval.types.AgentEvalRun` when set explicitly or when
                absent from loaded run metadata.

        Returns:
            Configured harness with :attr:`pairs` loaded and :attr:`agent_eval_run` metadata set;
            :attr:`scores` holds the :meth:`score_batch` output when ``score=True``, else ``None``.
        """
        client = client or Client()
        specs = None if evaluators is None else list(evaluators)
        harness_kw = dict(harness_kw)
        prompt_manifest = harness_kw.pop("prompt_manifest", None)
        prefix, data, target_for_eval, resolved = cls._prepare_langsmith_eval(
            target,
            dataset=dataset,
            client=client,
            evaluators=specs,
            experiment_prefix=experiment_prefix,
            limit=limit,
            existing_experiment_name=existing_experiment_name,
            for_aevaluate=False,
            **harness_kw,
        )
        if cls._langsmith_target_is_async(target_for_eval):
            return cls._run_arun_agent_eval_sync(
                target=target,
                dataset=dataset,
                client=client,
                evaluators=specs,
                experiment_prefix=experiment_prefix,
                limit=limit,
                max_concurrency=max_concurrency,
                existing_experiment_name=existing_experiment_name,
                harness_kw=harness_kw,
                prompt_manifest=prompt_manifest,
                score=score,
                score_metrics=score_metrics,
                include_per_pair=include_per_pair,
                fail_fast=fail_fast,
            )
        results = client.evaluate(
            target_for_eval,
            data=data,
            evaluators=resolved,
            experiment_prefix=prefix,
            max_concurrency=max_concurrency,
        )
        return cls._after_langsmith_eval(
            client,
            results=results,
            prefix=prefix,
            row_count=cls._sync_result_row_count(results),
            limit=limit,
            harness_kw=harness_kw,
            prompt_manifest=prompt_manifest,
            score=score,
            score_metrics=score_metrics,
            include_per_pair=include_per_pair,
            fail_fast=fail_fast,
        )

    @classmethod
    async def arun_agent_eval(
        cls,
        target: Any,
        *,
        dataset: str,
        client: Any | None = None,
        evaluators: Sequence[EvaluatorSpec] | None = None,
        experiment_prefix: str | None = None,
        limit: int | None = None,
        max_concurrency: int = 2,
        existing_experiment_name: str | None = None,
        score: bool = False,
        score_metrics: Sequence[str] | None = None,
        include_per_pair: bool = True,
        fail_fast: bool = False,
        **harness_kw: Any,
    ) -> SingleLLMEvalHarness:
        """LangSmith ``aevaluate`` entrypoint; supports sync and async ``target`` callables.

        Same two-phase flow, arguments, and return value as :meth:`run_agent_eval`.
        Required in notebooks and other async contexts when ``target`` is async (or use this
        instead of :meth:`run_agent_eval`, which delegates here via ``asyncio.run`` when possible).

        See :meth:`run_agent_eval` for parameter documentation.
        """
        client = client or Client()
        specs = None if evaluators is None else list(evaluators)
        harness_kw = dict(harness_kw)
        prompt_manifest = harness_kw.pop("prompt_manifest", None)
        prefix, data, target_for_eval, resolved = cls._prepare_langsmith_eval(
            target,
            dataset=dataset,
            client=client,
            evaluators=specs,
            experiment_prefix=experiment_prefix,
            limit=limit,
            existing_experiment_name=existing_experiment_name,
            for_aevaluate=True,
            **harness_kw,
        )
        results = await client.aevaluate(
            target_for_eval,
            data=data,
            evaluators=resolved,
            experiment_prefix=prefix,
            max_concurrency=max_concurrency,
        )
        return cls._after_langsmith_eval(
            client,
            results=results,
            prefix=prefix,
            row_count=await cls._async_result_row_count(results),
            limit=limit,
            harness_kw=harness_kw,
            prompt_manifest=prompt_manifest,
            score=score,
            score_metrics=score_metrics,
            include_per_pair=include_per_pair,
            fail_fast=fail_fast,
        )

    def _metric_names_to_run(self, extra: Sequence[str] | None) -> tuple[str, ...]:
        """Required metrics first, then any ``extra`` names not already listed (stable order)."""
        req = self._required_metrics
        if not extra:
            return req
        seen = set(req)
        out = list(req)
        for name in extra:
            if name not in seen:
                seen.add(name)
                out.append(name)
        return tuple(out)

    def register_metric(self, name: str, fn: MetricFn, *, strict_signature: bool = True) -> None:
        """Attach a custom scorer under ``name`` for use in ``metrics=`` or ``required_metrics``.

        The callable must accept exactly ``(case: EvalCase, result: RunResult)`` and return a
        mapping or Pydantic model instance. Put your primary value under a ``"result"`` key to
        surface it next to ``metric``; other keys become ``metadata``. When ``strict_signature``
        is true, arity is checked at registration time so bad signatures fail early.
        """
        if strict_signature:
            _validate_metric_fn(fn)
        self._custom[name] = fn

    def _run_builtin(self, name: str, case: EvalCase, result: RunResult) -> dict[str, Any]:
        """Look up ``name`` in ``_builtin_handlers`` and run the corresponding builtin."""
        handler = self._builtin_handlers.get(name)
        if handler is None:
            raise KeyError(f"Unknown built-in metric: {name}")
        raw = handler(case, result)
        if isinstance(raw, BaseModel):
            return raw.model_dump()
        return dict(raw)

    def score_one(
        self,
        case: EvalCase,
        result: RunResult,
        *,
        metrics: Sequence[str] | None = None,
        fail_fast: bool = False,
    ) -> dict[str, Any]:
        """Run each requested metric on a single ``(case, result)`` pair.

        Returns a dict whose keys are metric names. Each value is
        ``{"metric": "<id>", "result": ..., "metadata": {...}}`` - see class docstring. On scorer
        failure with ``fail_fast=False``, ``result`` is ``None`` and ``metadata`` is
        ``{"error": "..."}``.

        Args:
            case: Dataset row (inputs, optional expected labels, tags, ...).
            result: One completed model run for that row (must use ``result.case_id`` consistent
                with ``case.id`` in your own conventions; this method does not enforce equality).
            metrics: Additional metric names to run after the harness **required** metrics (same
                names as in ``required_metrics`` are ignored here). If ``None`` or empty, only
                required metrics run.
            fail_fast: If true, the first exception inside a metric propagates; if false, errors
                are captured per metric as described above.
        """
        names = self._metric_names_to_run(metrics)
        out: dict[str, Any] = {}
        for name in names:
            try:
                if name in self._custom:
                    raw = _normalize_metric_return(self._custom[name](case, result))
                else:
                    raw = self._run_builtin(name, case, result)
                out[name] = _wrap_score_block(name, raw)
            except Exception as e:  # noqa: BLE001
                if fail_fast:
                    raise
                out[name] = _wrap_score_block(name, {"error": str(e)})
        for block in out.values():
            MetricScoreBlock.model_validate(block)
        return out

    def score_batch(
        self,
        pairs: Sequence[tuple[EvalCase, RunResult]] | None = None,
        *,
        metrics: Sequence[str] | None = None,
        include_per_pair: bool = True,
        fail_fast: bool = False,
    ) -> dict[str, Any]:
        """Score many pairs, then compute batch-level rollups.

        For each tuple, calls ``score_one`` with the same ``metrics`` / ``fail_fast``. Then:

        1. ``rollup["operational"]`` - telemetry rollups from ``RunResult`` only (same shape as
           :func:`eval_harness.reporting.rollup_run_results`), independent of which scorers ran.
        2. ``rollup["metrics"]`` - batch rollups from each metric's ``result`` merged with
           ``metadata`` (see :func:`eval_harness._score_rollups.rollup_score_blocks`).

        Args:
            pairs: Ordered ``(EvalCase, RunResult)`` for each completed run you want scored.
                If omitted or ``None``, uses :attr:`pairs` from :meth:`from_pairs` (must be
                non-empty).
            metrics: Same as ``score_one`` - extra metrics merged with required; ``None`` means
                required only.
            include_per_pair: If false, the heavy ``per_pair`` list is omitted from the return value.
            fail_fast: Same as ``score_one``.
        """
        if pairs is None:
            if self._pairs is None:
                raise ValueError("No pairs have been loaded; pass pairs= or use from_pairs(...).")
            if len(self._pairs) == 0:
                raise ValueError("Loaded pairs are empty; cannot score an empty batch.")
            pair_list = list(self._pairs)
        else:
            pair_list = list(pairs)
        n = len(pair_list)
        score_rows: list[dict[str, Any]] = []
        per_pair_out: list[dict[str, Any]] = []
        for case, result in pair_list:
            scores = self.score_one(case, result, metrics=metrics, fail_fast=fail_fast)
            score_rows.append(scores)
            if include_per_pair:
                per_pair_out.append({**pair_row_identifier_fields(case, result), **scores})

        op = rollup_run_results(pair_list)
        metric_rollup = rollup_score_blocks(score_rows, self._metric_names_to_run(metrics))

        out: dict[str, Any] = {
            "n_pairs": n,
            "rollup": {"operational": op, "metrics": metric_rollup},
        }
        if include_per_pair:
            out["per_pair"] = per_pair_out
        ScoreBatchOutput.model_validate(out)
        return out
