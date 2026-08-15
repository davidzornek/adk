# Agent components by generate–evaluate–reflect pattern

This document names **concrete logical components** typically present when implementing each **generate–evaluate–reflect (GER)** pattern described in 2_generate_evaluate_reflect_patterns.md. It is descriptive, not prescriptive: products may merge roles, omit optional pieces, or map them to different frameworks (LangGraph, custom orchestrators, single multi-instruction prompts, etc.).

Read it in three layers:

1. **Contracts** — shared GER state and configuration; what gets written and validated between phases.
2. **Topology** — pattern sections: visible nodes vs internal calls, and where the loop closes.
3. **Operations (production)** — cross-cutting logging, metrics, rubric rollout, gates, and typical deployment placement (runtime vs adjacent services).

**Related:** pattern narrative and tradeoffs in 2_generate_evaluate_reflect_patterns.md; rubric- and judge-level signals in 4_general_agent_evaluation.md; GER-specific metrics in 3_generate_evaluate_reflect_evaluation.md. For a **LangGraph-shaped** reference implementation, see [sdg-agent/sdg_agent/base.py](../../../sdg-agent/sdg_agent/base.py) and [sdg-agent/docs/reflection_feedback_loop.md](../../../sdg-agent/docs/reflection_feedback_loop.md).

---

## Document conventions

- **Component** = a distinguishable responsibility (node, service, module, or clear sub-step), not necessarily a separate microservice.
- **Generator** = produces candidate artifact(s) from task context, constraints, and optional **grounding** (retrieval, seeds, style examples).
- **Evaluator** = scores or gates artifacts (rules, LLM-as-judge, hybrid); emits pass/fail and **rationales** consumable by humans or by **reflect**.
- **Reflector** = turns evaluation signal into **actionable feedback** for the next generate step (not only logging).
- **Sink** = persist, return to user, hand off to another subgraph, or enqueue for review—terminal for the GER slice unless a gate loops back.
- **Budget / stop policy** = caps on attempts, tokens, wall-clock, or "stop when all items pass"—defines loop termination alongside product rules.

GER **composes** with **routing** (which subgraph runs) and **planner–executor** (how work is decomposed); this document stays inside the GER subgraph. See 2_generate_evaluate_reflect_patterns.md §5.

---

## Shared foundation

### GER state

Carry task context, candidates, verdicts, and retry bookkeeping across generate, evaluate, reflect, and sink. Field names vary by codebase; treat the list below as a **logical** schema.

| Field (logical) | Typical role |
|---|---|
| Task / request | What to produce: prompt, structured task spec, ticket id, planner-emitted work item, etc. |
| Grounding payload (optional) | Retrieved passages, seed examples, style references, tool outputs the generator must respect. |
| `**rubric_id** / criteria version (optional)**` | Which rubric or policy snapshot applied; supports replay and drift analysis. |
| Candidate artifacts | Current batch of outputs (text, records, tool args)—may be a list with stable ids per slot. |
| `**eval_verdict** per candidate (or aggregate)**` | Pass/fail, scores, structured criterion breakdown. |
| `**eval_rationale** per candidate**` | Short natural-language or structured reasons; **reflect** and human triage depend on quality here. |
| `**reflection_feedback** (optional)**` | Instructions for the **next** generate pass, usually scoped to failed slots or global "fix these themes." |
| `**attempt_index** / per-slot attempt counts**` | How many generate→evaluate cycles have run; enforces budgets. |
| `**budget_remaining** (optional)**` | Token, cost, or time budget for the loop. |
| `**stop_reason** (optional)**` | e.g. `all_pass`, `max_attempts`, `budget_exhausted`, `user_abort`, `gate_rejected`. |
| `**accepted_artifacts** / rejected_artifacts (optional)**` | Split view when partial success is allowed—drives sink and quarantine paths. |
| Gate status (optional) | Pending human approval, rules-engine decision, workflow id—see gated pattern. |
| Trace metadata | Correlation ids, model and prompt versions per phase, timestamps—supports 3_generate_evaluate_reflect_evaluation.md and incident attribution. |

### GER configuration

Centralize wiring so behavior stays **data-driven** where possible:

- **Rubric / criteria** — static prompt files, dynamic rubric builders, or external policy services; alignment with 4_general_agent_evaluation.md (judge stability, human alignment).
- **Model and tool routing** — which endpoints or models run generate, evaluate, and reflect (often different cost/latency tiers).
- **Retry policy** — max attempts per request, per item in a batch, global caps; whether to regenerate **only failed slots** or full batch.
- **Partial success semantics** — write passing rows only, quarantine failures, or fail the whole batch.
- **Reflection contract** — required shape of feedback (bullets, JSON patches, natural language) so the generator prompt can consume it reliably.
- **Gate hooks (optional)** — integration ids for human review, approval workflows, or regulated sign-off before sink.

### Criteria / rubric registry (optional, mature systems)

A single **source of truth** for rubric ids, versions, and ownership—mirrors the idea of a route registry in routing docs. Reduces skew between evaluator prompts, offline eval datasets, and dashboards.

---

## Pattern — Linear pipeline (no retry)

State touchpoints: After **generate**, state holds **candidates**; **evaluate** writes **verdicts** and **rationales**; sink consumes accepted (or all) artifacts. No `reflection_feedback` loop; failures exit to logging, quarantine, or routing elsewhere.

| Component | Role |
|---|---|
| Entry / task adapter | Normalizes incoming payload into the task + context shape the generator expects (planner output, user message, batch job row). |
| Grounding provider (optional) | Retrieval, tool calls, or example fetch **before** or **inside** generate; writes **grounding payload** into state. |
| Generator | Produces **candidate artifacts** under task and grounding constraints. |
| Evaluator | Applies rubric/policy; writes `eval_verdict` and `eval_rationale` per candidate (or aggregate batch verdict). |
| Post-eval router (optional) | Product logic: if any fail, route to human queue, fallback agent, or hard error—**not** the same as closed-loop reflect. |
| Sink | Persist, API response, downstream tool, or handoff; may write only passing items per partial success config. |
| Metadata writer | Records versions, latency per phase, and headline pass rate for observability. |

**Graph topology (external view):** `START → generate → evaluate → sink → END` (with optional grounding pre-step).

---

## Pattern — Closed-loop retry

State touchpoints: Evaluate drives a **conditional**: if not all pass and **budget** allows, **reflect** writes `reflection_feedback`, generator runs again (often for failed slots), then evaluate again. Loop until `all_pass`, budget exhausted, or stop policy fires.

| Component | Role |
|---|---|
| Entry / task adapter | Same as linear pattern. |
| Grounding provider (optional) | Same; may refresh grounding between attempts if product allows. |
| Generator | Initial and subsequent passes; must accept `reflection_feedback` and prior failed candidates as context when configured. |
| Evaluator | Same contract as linear; per-attempt traces are critical for debugging loops (3_generate_evaluate_reflect_evaluation.md §1). |
| Stop policy / budget controller | Centralizes `attempt_index`, caps, and `stop_reason`; may be a dedicated node or framework-level loop guard. |
| Conditional (loop head) | Reads verdicts + budget; chooses **sink** vs **reflect** vs **fail closed**. |
| Reflector | Consumes `eval_rationale` (and optionally criterion breakdown); emits `reflection_feedback` mapped to the generator's expected format. |
| Failed-slot selector (optional) | For batch generation, marks which indices to regenerate vs carry forward passes—reduces cost and avoids rewriting good rows. |
| Sink | After loop exit: persist `accepted_artifacts`; optionally attach `rejected_artifacts` or quarantine references when budget exhausted with residual failures. |
| Loop metadata writer | Per-attempt logs: verdicts, reflection snippets, attempt counts—supports yield and attribution metrics. |

**Graph topology (external view):** `generate → evaluate → (conditional) → (reflect → generate → evaluate)* → sink → END`.

**Failure modes to instrument:** vague reflections, evaluator–generator blind spots, oscillation (improve then regress)—see tradeoffs in 3_generate_evaluate_reflect_evaluation.md §2.

---

## Pattern — Gated or supervised

Composes with linear or closed-loop: after automated evaluation (and optional retries), a **gate** must allow progress before sink or user delivery.

State touchpoints: Adds **gate status**, approver identity or workflow id, and possibly human-edited rubric or artifact versions.

| Component | Role |
|---|---|
| Automated GER subgraph | Linear or closed-loop as above, up to the point of "candidate ready for release." |
| Gate | Human queue UI, approval API, rules engine, or second-line policy check; may **block, approve, send back** with comments, or **edit** criteria/artifacts. |
| Escalation / quarantine sink (optional) | Path for timeouts, rejections, or compliance holds—distinct from happy-path sink. |
| Audit / versioning writer | Records who approved what, rubric version at approval time, and diff from raw model output when required for regulated flows. |

**Graph topology (external view):** `... → evaluate [+ retry loop] → gate → sink → END` (with branches for reject/quarantine).

---

## Cross-cutting production components

These surround any GER shape: logging, metrics, rollout, and safety adjacent to the loop.

| Component | Role |
|---|---|
| Structured GER traces | Per attempt: candidate ids, `eval_verdict`, `eval_rationale` (or hashes), reflection summary, model/prompt versions—aligned with 3_generate_evaluate_reflect_evaluation.md. |
| Metrics and dashboards | GER yield, residual failure rate, attempts-to-pass, cost/latency by phase; judge calibration signals from 4_general_agent_evaluation.md. |
| Rubric and config rollout | Versioned rubrics, feature flags, canary on evaluator or generator prompts independent of graph topology. |
| Safety and guardrails | May live **inside** evaluator, **beside** it, or after sink; log disagreements between rubric pass and safety fail (4_general_agent_evaluation.md §3). |
| Human operations | Playbooks for gate queues, rubric change approval, and triage of exhausted-retry cases. |

---

## Typical deployment placement (managed agent runtime)

Illustrative only: maps logical GER components to an **agent process / managed runtime** versus **adjacent services**. Not a vendor contract; boundaries vary by product.

| Bundle | Typically inside managed runtime | Typically outside / adjacent |
|---|---|---|
| Orchestration & graph | Entry adapter, **generate / evaluate / reflect steps** (or combined nodes), conditional loop, stop policy, sink invocation, gate client calls. | — |
| Policy & retry (code) | Budget checks, partial-success logic, **failed-slot selector**, in-memory GER configuration snapshot. | — |
| Rubric / criteria | Loaded prompts and schemas; optional dynamic rubric builder running in-process. | **Source of truth** for rubric artifacts (Git, CMS, policy service); approved criteria registry databases. |
| Models | Thin clients for generator, evaluator, reflector LLMs. | **Model serving** APIs; fine-tuned judge endpoints. |
| Grounding | Orchestration of tool/retrieval calls. | Search, vector DB, document stores, feature pipelines. |
| GER state | Turn/batch payload held by runtime. | Long-lived storage for quarantine, audit, or human queues. |
| Gates | Request/response to gate service; UI is external. | **Human review** apps, ticketing, **approval workflow** engines. |
| Observability | Emit traces and metrics from running steps. | Log/metric **backends**, eval pipelines, offline replay jobs. |

*Offline eval and rubric calibration (datasets, human labels) usually live **outside** the hot request path; the runtime may emit samples to those systems.*

---

## Quick reference and reconciliation checklist

### Graph-visible nodes by pattern

| Pattern | Typical graph-visible nodes (beyond adapters) |
|---|---|
| Linear | Generate → evaluate → sink (optional grounding step before generate). |
| Closed-loop retry | Generate → evaluate → conditional → reflect (on branch) → loop; then sink. |
| Gated / supervised | GER subgraph as above → gate → sink (plus reject/quarantine branches). |

### Minimal component checklist (by pattern)

| Pattern | Contracts | Topology core | Production surround (typical) |
|---|---|---|---|
| Linear | GER state + configuration | Generator, evaluator, sink | Traces, pass-rate metrics, rubric versioning |
| Closed-loop | Same + attempt / budget fields | + Reflector, conditional, stop policy | Per-attempt traces, yield and residual-failure metrics |
| Gated | Same + gate fields | + Gate + audit path | Human ops, escalation sinks, approval logging |

### Reconciliation checklist (compare two writeups)

When merging another breakdown of "GER components," align on:

1. Where generate, evaluate, and reflect run (one prompt vs separate nodes/services).
2. What is written to state after each phase (shared foundation).
3. Retry granularity (whole batch vs failed slots only) and stop rules.
4. Reflection input/output contract and how it is merged into the next generate prompt.
5. Partial success semantics at sink.
6. Gate placement and whether automated retries run before or after human visibility.
7. Instrumentation for eval (4_general_agent_evaluation.md) vs GER loop (3_generate_evaluate_reflect_evaluation.md).
