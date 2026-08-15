# Agent components by planner–executor pattern

This document names **concrete logical components** typically present when implementing each planner–executor pattern described in 2_planner_executor_patterns.md. It is descriptive, not prescriptive: products may merge roles, omit optional pieces, or map them to different frameworks (LangGraph, custom orchestrators, etc.).

Read it in three layers:

1. **Contracts** — shared planner-executor state and configuration; what gets written and validated before and during tool use.
2. **Topology** — pattern sections: graph-visible nodes vs tight internal loops.
3. **Operations (production)** — cross-cutting logging, metrics, safety, config rollout, optional plan data stores, and typical deployment placement (runtime vs adjacent services).

**Related:** pattern tradeoffs in 1_planner_executor_cheatsheet.md; what to measure in 3_planner_executor_evaluation.md. **Routing** decides which subgraph runs (4_routing_agent_components.md); this doc applies inside that subgraph once work is decomposed into plan vs execute. For a minimal **Python sketch** (frozen state, LangChain Runnable bases, abstract hooks per pattern), see `planner_executor_base_classes/` plus `pyproject.toml` (`langchain-core`). Same spirit as the dependency-free `routing_base_classes/` for routing.

---

## Document conventions

- **Component** = a distinguishable responsibility (often a node, service, module, or clear sub-step), not necessarily a separate microservice.
- **Planner** = produces or updates **intent**: next step(s), tool choices, parameters, ordering, stop conditions—explicit plan artifact and/or per-turn intent.
- **Executor** = carries intent out: invokes tools, handles errors, writes observations, signals completion or failure.
- **Plan artifact** = structured representation of intended work (checklist, DAG, JSON steps)—may be user-visible or internal only.
- **Gate** = human, rules engine, or second model that **approves, edits, or rejects** a plan (or batch) **before** authorized execution.
- **Tool runner** = concrete invocation layer (API client, sandbox, MCP, subgraph entrypoint) the executor calls.

Patterns compose: gated planning layers on top of either **interleaved** or **plan-then-execute** execution shapes. **Hybrid UX** (summary plan shown to the user while an interleaved engine runs) is still interleaved at execution; state may carry both a **display plan** and **authorized execution intent**—see Hybrid and §5 in 2_planner_executor_patterns.md. Nested route-like dispatch inside a planner (specialist choice before steps are fixed) reuses routing concepts at a finer grain; see 4_routing_agent_components.md when that dispatch is first-class.

---

## Shared foundation

### Planner–executor state

Carry task context, plans, authorizations, and execution trace across planner, gate, and executor. Field names vary by codebase; treat the list below as a **logical** schema.

| Field (logical) | Typical role |
|---|---|
| Raw / normalized task context | User ask, session, product surface, auth tier, attachments—inputs the planner reads. |
| `**plan_artifact** (optional)**` | Full or partial structured plan: steps, dependencies, tool ids, parameters—especially in **plan-then-execute**. |
| `**next_intent** / per-turn plan slice**` | In **interleaved** flows: the single next action or tiny horizon the executor may run immediately. |
| `**plan_id** / plan_version**` | Identity for the current plan for replay, diffing after edits, and correlating logs across replans. |
| `**authorized_steps** / authorized_plan**` | Subset of the plan **after** validation and any gate; executor must not run outside this without a new authorization event. |
| `**executed_steps** / tool trace**` | Ordered record of tool calls, arguments (or hashes), results, errors—supports plan-execution alignment metrics. |
| Per-step observations | Summaries or raw outputs attached to step ids for replanning and user display. |
| `**replan_count** / replan_trigger**` | Why the planner ran again (tool failure, policy, user edit, timeout). |
| `**gate_status** (optional)**` | e.g. pending, approved, edited, rejected, expired. |
| `**gate_actor** / gate_reason (optional)**` | Who or what authorized the plan; short rationale for audit. |
| `**display_plan** (optional)**` | User-facing summary that may **lag** true execution intent in hybrid UX. |
| Trace metadata | Correlation ids, planner / executor / gate model and prompt versions, timestamps—supports replay and 3_planner_executor_evaluation.md. |

### Planner–executor configuration

Centralize behavior so plan and execution stay **data-driven** where possible:

- **Plan schema** and versioning (fields, tool parameter shapes, DAG vs linear list).
- **Tool registry** with risk tiers, allowlists/denylists per tenant or surface, and which tools require a gate.
- **Replan policy** — max iterations, backoff, which errors trigger replan vs abort vs escalate.
- **Parallelism rules** — when independent branches from a plan may run concurrently; merge semantics.
- **Planner vs executor model** (or single model) ids, temperatures, and budgets.
- **Gate configuration** — SLA targets, auto-approval rules, required human roles, retention for audit.

This aligns with plan validator inputs, executor walker behavior, and gate rules in the pattern tables below.

---

## Pattern — Interleaved plan-act (tight loop)

Planning and execution **alternate** frequently—sometimes every tool call. At the graph level this often cycles: `plan_step → execute_step → observe → (replan or finish)`.

State touchpoints: Each iteration reads **task context** and **prior observations**; writes `**next_intent**` (or equivalent), then appends to `**executed_steps**` and observations; updates `**replan_***` when the loop continues.

| Component | Role |
|---|---|
| Entry state adapter | Normalizes incoming payload into the state shape the loop expects. |
| Loop controller | Decides continue vs finish vs escalate; enforces max steps, timeouts, and replan limits from configuration. |
| Planner step | Produces **next intent** (and optional scratchpad): tool name, args, short rationale—implemented as a dedicated node, a phase inside one agent node, or a prompt role. |
| Planner output parser / schema validator | Ensures planner output maps to known tools and parameter shapes before execution. |
| Executor step | Invokes the **tool runner** for the chosen action; catches errors and timeouts. |
| Observation writer | Records results into state for the next planner turn; may summarize for token limits. |
| Working memory (optional) | Scratchpad or message pruning so the planner does not lose prior attempts (reduces thrashing). |
| Plan-execution metadata writer | Logs per-iteration intent vs actual tool call for eval and incident triage. |
| Graph topology (external view) | From one graph-visible "agent" node with an internal loop, up to explicit `**plan_step**` ↔ `execute_step**` nodes with a cycle edge—both are common. |

---

## Pattern — Plan-then-execute (batched plan artifact)

The system first produces a **plan artifact**, then an **executor** walks it—with replanning as an explicit branch back to planning.

State touchpoints: `**plan_artifact**` is written after the plan node; `**authorized_steps**` reflects post-validation / post-gate truth; `**executed_steps**` fills as the walker progresses; `**replan_trigger**` clears or increments when returning to the planner node.

| Component | Role |
|---|---|
| Plan producer node | LLM, template, or hybrid: emits structured plan (steps, dependencies, tool ids). |
| Plan schema validator | Rejects or repairs malformed plans; enforces registry and typing. |
| Static plan policy checker | Rules over the **whole** plan: forbidden tools, scope, cost caps, tenancy—feeds plan-stage violations signals. |
| Executor walker | Walks the plan sequentially or schedules **parallel branches** where dependencies allow; invokes tool runner per step. |
| Branch scheduler (optional) | For DAG-shaped plans: queue ready steps, respect parallelism limits, collect partial failures. |
| Merge / synthesize node (optional) | Combines parallel branch outputs before final response or next plan. |
| Replan edge / condition | On failure, stale plan, or user edit: jump back to plan producer with preserved `**executed_steps**` and observations for context. |
| Partial execution state (optional) | Checkpoint which step ids completed so resume after crash or long-running jobs does not duplicate side effects. |
| Graph topology (external view) | Often `plan_node → [validate] → execute → [merge] → END` with a conditional edge `execute → plan_node` on replan. |

---

## Pattern — Gated or supervised planning

A gate sits **between** plan output and tool execution. Composes with **interleaved** (gate each batch or sensitive step) or **plan-then-execute** (gate full artifact).

State touchpoints: Writes `**gate_status**`, `**gate_actor**`, and updates `**authorized_steps**` to match approved or edited content; executor reads **only** authorized portions.

| Component | Role |
|---|---|
| Gate queue / UI (human) | Surfaces plan diff, risk labels, and approve/edit/reject actions; enforces identity and authorization. |
| Automated gate | Rules engine or second model that approves, patches, or rejects against policy; must log version and rationale. |
| Plan diff engine (optional) | Represents edits relative to proposed plan for audit and post-approval execution failure analysis. |
| Authorization snapshot writer | Persists the **exact** authorized plan slice and version id the executor must follow. |
| Executor admission check | Last line before tools run: rejects calls that are not in `**authorized_steps**` (defense in depth). |
| Gate audit log | Immutable or append-only record for compliance joins (who, when, what changed). |
| Timeout / escalation (optional) | If human gate stalls: expire, default deny, or route to fallback per product policy. |

---

## Pattern — Hybrid: display plan + interleaved engine

Rich products often run an **interleaved** executor while surfacing a **summary plan** to the user, updated lazily (§5 in 2_planner_executor_patterns.md).

State touchpoints: `**display_plan**` may differ from `**authorized_steps**` / `**next_intent**`; instrumentation should not conflate them in eval or logs.

| Component | Role |
|---|---|
| Summary / narrative planner (optional) | Produces or refreshes user-facing steps for transparency without binding execution order if the internal loop adapts. |
| Display sync policy | When to update the visible plan (every N tools, on replan, on user ask)—avoids misleading UX when intent diverges. |
| Authorized execution path | Same as interleaved or plan-then-execute: `**authorized_steps**` or per-turn intent remains the source of truth for tools. |
| Consistency checks (optional) | Product-level rules so display text does not promise actions the executor will not take. |

Graph topology (external view): Often overlaps with interleaved; may add a lightweight "update UI plan" side effect or node on a schedule.

---

## Plan artifact store (optional, mature systems)

Supports training labels, drift detection, and compliance—not required for prototypes. Analogous in spirit to the routing classification data store.

- **Versioned plans:** plan_id, schema version, raw artifact, proposed vs authorized diffs.
- **Labels:** human or automated plan adequacy judgments tied to task ids.
- **Execution join:** link plans to `**executed_steps**` and outcomes for offline analysis aligned with 3_planner_executor_evaluation.md §1.2–1.3.

---

## Cross-cutting production components

These surround any pattern: observability, rollout, safety, and human-gate operations.

| Component | Role |
|---|---|
| Structured planner-executor logs | Task id, plan_id, hashes of plan and authorized slice, gate outcome, replan reasons, per-step tool ids and latency—aligned with eval must-haves in 1_planner_executor_cheatsheet.md. |
| Metrics and dashboards | Replan rate, plan-execution alignment proxies, gate SLA, cost/latency split planning vs execution—see 3_planner_executor_evaluation.md. |
| Config and rollout | Versioned plan schema, tool registry, gate rules; safe rollback when planner prompts change. |
| Pre-execution safety | Plan-level denylists and caps independent of final-output guardrails; catches disallowed tools before invocation. |
| Human-gate operations | Queues, staffing alerts, audit export, integration with ticketing when plans are rejected or edited at volume. |

---

## Typical deployment placement (managed agent runtime)

Illustrative only: maps logical components to an **agent process / managed runtime** (e.g. AWS AgentCore-style execution) versus **separate services**. Not a vendor contract; boundaries vary by product and networking.

| Bundle | Typically inside managed runtime | Typically outside / adjacent |
|---|---|---|
| Orchestration & graph | Interleaved loop controller, plan / execute nodes, conditional replan edges, merge, executor admission. | — |
| Planner / executor logic (code) | Parsers, validators, walker, tool runner orchestration, automated gate code paths. | — |
| Model inference | Thin clients and response handling. | **Weights and serving** for planner, executor, or gate LLMs. |
| Human gate | Callbacks / webhooks that resume the graph when approval arrives. | Reviewer UI, identity, queueing, and notification systems. |
| State | Turn/session payload the runtime holds (see planner-executor state). | Durable store for long jobs, plan artifact store, or cross-session checkpoints. |
| Configuration | Config snapshots loaded at deploy or refresh. | **Source of truth** for planner-executor configuration (parameter store, Git, feature-flag service). |
| Observability | Emit structured logs and metrics from running code. | **Log/metric backends** and dashboards. |
| Analytics / eval pipelines | — | Offline joins from plan artifact store and trace exports. |

---

## Quick reference and reconciliation checklist

### Graph-visible nodes by pattern

| Pattern | Typical graph-visible nodes (beyond tools) |
|---|---|
| Interleaved | Loop as one agent node or explicit `**plan_step**` ↔ `execute_step**` cycle. |
| Plan-then-execute | Plan → validate (optional) → execute → merge (optional); replan edge to plan. |
| Gated | Plan → gate (human wait or automated) → execute; may repeat plan after rejection. |
| Hybrid | Same as interleaved (or plan-then-execute) plus optional display plan update hook. |

### Minimal component checklist (by pattern)

| Pattern | Contracts | Topology core | Production surround (typical) |
|---|---|---|---|
| Interleaved | State + tool registry | Loop controller + planner + executor + observation writer | Logs, replan limits, cost split |
| Plan-then-execute | Same + plan schema | Plan producer + validator + walker + replan edge | Plan-stage policy metrics, partial resume if needed |
| Gated | Same + authorization snapshot | Gate + admission check + executor | Audit log, human SLA, post-approval failure tracking |
| Hybrid | Same + `**display_plan**` policy | Core pattern + display sync | UX consistency checks, separate eval for "what user saw" vs "what ran" |

### Reconciliation checklist (compare two writeups)

When merging another breakdown of "planner-executor components," negotiate the following:

1. Where the plan is produced (every turn vs batched node) and whether a **display plan** exists.
2. What is authorized before tools run and where `**authorized_steps**` is written (gate vs validator only).
3. How replanning is triggered and what state is passed back to the planner.
4. How execution is traced so plan-execution alignment and per-step failures are measurable (3_planner_executor_evaluation.md).
5. Orthogonality to routing — subgraph entry is chosen upstream (4_routing_agent_components.md); this doc starts after that boundary unless **nested dispatch** is explicitly in scope.
