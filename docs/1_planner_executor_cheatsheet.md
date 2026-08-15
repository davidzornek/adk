# Planner–executor cheatsheet

**Quick reference:** logical vs structural vs organizational split, three implementation patterns (interleaved plan-act, plan-then-execute, gated or supervised planning), runtime vs adjacent placement (e.g. managed agent runtime), composition with routing, and a **yes / no decision flow** for which pattern fits. Full narrative and example: 2_planner_executor_patterns.md. Metrics and evaluation: 3_planner_executor_evaluation.md. Concrete components per pattern (nodes, state, gates, deployment): 4_planner_executor_agent_components.md. Runnable sketch walkthrough: 5_planner_executor_usage_demo.ipynb.

---

## Quick maps

These tables are **compressed outcomes**. More detail below: **Pros and cons** (strengths and risks), **Evaluation must-haves**, **Runtime vs adjacent**, **Composition with routing**, the full **Decision flow** (Part 1–2 and notes), and **minimal trace hooks**. Longer narrative: 2_planner_executor_patterns.md.

**Quick map — split type**

| Type | What it is | What it buys |
|---|---|---|
| Logical | Roles and phases mainly in prompts or conventions; one node or service may still run both | Fast to ship; you can still test plan vs act in eval |
| Structural | Distinct prompts, nodes, or packages; explicit **plan artifact** or state handoff | Clear traces, graph-level replan and gates |
| Organizational | Different owners for schemas, releases, or on-call ("bad plan" vs "failed tool") | Contract discipline: versioning, review gates, eval ownership |

**Quick map — pattern choice**

| Lean toward... | When... |
|---|---|
| Interleaved plan-act | Partial information, tool outcomes drive the next move, little need for a stable upfront user-visible plan |
| Plan-then-execute | Auditable intent, batch policy checks on a full plan, or safe parallel branches |
| Gated / supervised | High stakes, regulated flows, or human / second-line approval before irreversible tools |

**Quick map — composed shape**

| Pre-execution gate? | Upfront / batched plan? | Shape |
|---|---|---|
| No | No | Interleaved plan-act |
| No | Yes | Plan-then-execute |
| Yes | No | Gated + interleaved plan-act |
| Yes | Yes | Gated + plan-then-execute |

These compose: e.g. batched plan for display with interleaved replanning on failure, plus a gate only on sensitive tools (see §6 in 2_planner_executor_patterns.md).

---

## Pros and cons at a glance

| Pattern | Brief description | Strengths | Risks |
|---|---|---|---|
| Interleaved plan-act | Short horizon; plan and execute alternate in a loop | Fast adaptation; minimal upfront commitment | Weaker upfront visibility; possible thrashing |
| Plan-then-execute | Full or multi-step plan artifact before bulk execution | Auditable intent; parallelization; batch policy checks | Stale plans; replan/merge complexity |
| Gated / supervised planning | Approval or policy gate before execution | Safety and compliance; clear audit trail | Latency; gate quality and maintenance |

In practice, we expect non-trivial products to **blend** these patterns: e.g., batched plan for user display with interleaved replanning on failure, plus gates only for sensitive tools or environments.

---

## Evaluation must-haves

Minimum planner-executor-specific signals to combine (plan vs execution attribution, gates, cost). Full signal list, judges, and tradeoffs: 3_planner_executor_evaluation.md.

| Must-have | What it answers |
|---|---|
| Plan-execution alignment | Whether **executed** steps match **authorized** plan or per-turn intent (order, tools, no extras). |
| Plan adequacy on a labeled set | Whether plans match a maintained reference for multi-step tasks—analogous to routing labels. |
| Replan rate and triggers | How often plans are discarded mid-run and why (failure, policy, user edit). |
| Task success by pattern / phase | Whether one shape (interleaved vs batched vs gated) regresses when products blend patterns. |
| Plan-stage policy violations | Disallowed tools or scope in the **plan** before execution—not only final output checks. |
| Cost and latency: planning vs execution | Whether model or API split across phases behaves as designed. |
| Gate metrics (when gated) | Pass/reject/edit rates, time-to-approval, post-approval execution failures. |

Routing evaluation (3_routing_evaluation.md) stays **orthogonal**: measure planning and execution **inside** the subgraph that routing selected.

For non-deterministic planners (LLM or stochastic policy), add **plan stability on a replay set** after model, prompt, or temperature changes. When planning is driven by untrusted or semi-trusted inputs, add **plan-stage safety** and "plan escape" / injection probes (see §1.2 and §1.6 in 3_planner_executor_evaluation.md).

---

## Runtime vs adjacent (e.g. managed agent runtime)

Illustrative map: what usually runs **inside** a managed agent runtime versus **outside** it. Not a platform guarantee—see the full grouped table and caveats under Typical deployment placement.

| Bundle | Usually in runtime | Usually outside / adjacent |
|---|---|---|
| Orchestration & graph | Interleaved loop, plan / execute / replan nodes, merge, executor admission | — |
| Planner / executor logic (code) | Parsers, validators, walker, tool runner, automated gate paths | — |
| Model inference | API clients and response handling | **Serving** for planner, executor, or gate LLMs |
| Human gate | Callbacks / webhooks that resume when approval arrives | Reviewer UI, identity, queueing, notifications |
| State & config | Session/turn state in flight; config **loaded** | Durable jobs, plan artifact store, config source |
| Observability | Emit logs/metrics | Backends & dashboards |
| Analytics / eval | — | Offline joins from plan artifact store and trace exports |

---

## Composition with routing

- Routing = *which* agent or subgraph handles the request; planner-executor = *how* that subgraph decomposes goals and tools.
- A router can send "hard" work to a **plan-then-execute** subgraph and "easy" work to a single-shot path with no separate planner.
- Hybrid UX: interleaved execution internally plus a **summary plan** surfaced and updated lazily.
- A planner may embed **router-like dispatch** (specialist, template) before steps are fixed—**nested composition**, consistent with the split if dispatch is intent before committed execution (reopened on replan only).

---

## Decision flow (yes / no)

Use this as a checklist, not a policy.

### Part 1 — Is planner-executor appropriate?

Answer in order.

| # | Question | If No | If Yes |
|---|---|---|---|
| 1.1 | Does the workflow involve **multiple tool steps, replanning, or ordering choices** where distinguishing intent from execution helps? | Stop: a single-shot path or minimal loop may be enough without a planner-executor story. | Continue to 1.2. |
| 1.2 | Do you need **separate accountability or observability** for what was **intended** vs what ran, or to use **different models or prompts** for planning vs acting? | You can still use **interleaved** plan-act with light conventions; a **structural** split is optional. | Treat planner-executor as **first-class** — go to Part 2. |

**Summary:** Prefer an explicit split when work is **multi-step** and **attribution** (plan vs execution), **governance**, or **model routing** benefits from separation. Full definitions: §1–§2 in 2_planner_executor_patterns.md.

### Part 2 — Which pattern?

Assume Part 1 ended with first-class planner-executor, or you are choosing shape for a subgraph that already uses the split. Answer 2.1, then 2.2.

| # | Question | If No | If Yes |
|---|---|---|---|
| 2.1 | Must a human, rules engine, or second model approve, edit, or reject plans (or batches of steps) **before** sensitive or irreversible tools run? | Continue to 2.2. | **Gated / supervised** — gate sits between plan output and tool execution; then apply **2.2** for the execution shape underneath. |
| 2.2 | Do you need a **stable plan artifact up front** (user-visible steps, batch policy checks on the whole plan, or **parallel** independent branches with explicit merge)? | **Interleaved plan-act** — short horizon; plan and execute alternate. | **Plan-then-execute** — produce plan (or batch), then walk it with replan triggers as needed. |

**Notes**

- **Gated** composes with either execution shape: gate semantics are the same; only whether the plan is **per-batch / tight loop** vs **batched artifact** changes.
- Hybrid UX (summary plan + interleaved engine) is still **interleaved** at execution with a lazy user-facing plan—see §5 in 2_planner_executor_patterns.md.
- Logical vs structural vs organizational split (§1) is mostly independent of which pattern you pick.
- This flow does not replace **routing** (which subgraph owns the turn); it applies **inside** a routed capability. See **Composition with routing** above and §5.
- **Components and deployment** — node/state breakdown and runtime placement: 4_planner_executor_agent_components.md; hybrid display plan + interleaved engine: Hybrid.

---

## Minimal trace / contract hooks

Full narrative: §2, patterns: §4.

| What to separate | Why |
|---|---|
| Planned steps (artifact or per-turn intent) vs executed tool calls and observations | Replay, incident triage ("bad plan" vs "failed tool"), eval of planning quality vs execution |
| Replan or gate events (who authorized, what changed) | Attribution when behavior shifts mid-run |
