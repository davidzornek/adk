# Evaluation Paradigm for Planner–Executor

## Overview

This document outlines a candidate evaluation paradigm for planner-executor systems: workflows that separate **what to do next** (planning: steps, tools, ordering) from **doing it** (execution: tool calls, observations, completion). It covers **planner-executor-specific** signals only—tied to plan quality, execution fidelity, replanning, and gates. End-to-end task quality for domains unrelated to planning structure, **routing** (which subgraph owns the turn), and **generate-evaluate-reflect** pipelines belong in their own evaluation work; see 3_routing_evaluation.md and sibling narrative where relevant (e.g. 2_generate_evaluate_reflect_patterns.md).

For each signal class we distinguish:

- **Quantitative** – automatically computed counts and aggregates.
- **LLM-judge / model-judge** – automatable qualitative checks using models as judges.
- **Human-in-the-loop** – human ratings, trace reviews, and policy refinement.

---

## 1. Planner–executor-specific signals

These assume a **meaningful planning phase** (explicit plan artifact, per-turn intent, or gated approval before tools)—even when planner and executor share a runtime or model.

### 1.1 End-to-end outcomes (plan-aware)

**Quantitative**

- **Task success stratified by pattern or phase mix**
  - Why: When products blend interleaved plan-act, plan-then-execute, and gated flows, aggregate success can hide regressions on one shape (e.g. batched plans failing after a replan change).
  - When: Whenever multiple shapes coexist or you are migrating between them.
- **Steps or tool calls to completion (conditional on success)**
  - Why: Detects thrashing in **interleaved** loops or bloated plans in **plan-then-execute**; complements latency and cost.
  - When: Always for tool-heavy workflows; especially after planner or tool-schema changes.
- **Replan rate and replan triggers**
  - Why: Measures how often execution failures or policy force a new plan; high rates may indicate weak planning, flaky tools, or mis-set replan thresholds.
  - When: When replanning is explicit; after executor or environment changes.

**LLM-judge / model-judge**

- **Model-judged "was this plan reasonable for the task?" on samples**
  - Why: Cheap proxy when human plan labels are sparse; flags obviously wrong step order, missing steps, or wrong tools **before** blaming execution.
  - When: When planning is LLM-driven and you need scalable triage.

**Human-in-the-loop**

- **Human review of full traces (input → plan → execution → outcome)**
  - Why: Gold standard for attributing failures to **bad plan, bad execution, or bad task spec**; aligns with incident response and product expectations.
  - When: Before high-stakes launch; after planner or gate policy changes.

### 1.2 Plan quality and policy (planning component)

**Quantitative**

- **Plan-level policy violation rate**
  - Why: Counts plans that include **disallowed tools**, out-of-scope actions, or schema violations **before** execution—distinct from downstream output guardrails.
  - When: When static or rule checks run on plan artifacts or structured planner output.
- **Plan adequacy vs canonical reference (labeled set)**
  - Why: On a maintained set of tasks with **acceptable plan sketches** (steps, tools, ordering), measures whether the planner's output matches or subsumes the reference—analogous to misrouting labels for routing.
  - When: Once you have even a small labeled set; essential for claiming "planning quality" improvements.
- **Plan stability on a replay set**
  - Why: For LLM (or stochastic) planners, checks whether plans for fixed inputs stay stable enough for regression testing; unstable plans make execution metrics noisy.
  - When: After planner model, prompt, or temperature changes.

**LLM-judge / model-judge**

- **Auxiliary check: "does the plan respect stated constraints?"**
  - Why: Flags plans that ignore user constraints, data scope, or rubric when those are explicit in context.
  - When: When constraint following is a product requirement but full labeling is expensive.

**Human-in-the-loop**

- **Human-labeled micro-dataset for plan adequacy**
  - Why: Canonical "good enough plan" labels per task class; supports calibration, drift detection, and debate resolution between automation and product.
  - When: For long-lived planners in quality- or compliance-sensitive flows.

### 1.3 Execution fidelity (relative to intent)

**Quantitative**

- **Plan-execution alignment rate**
  - Why: Measures whether **executed** steps match **authorized** plan (or per-turn intent): skipped steps, extra calls, wrong order, or unapproved tools.
  - When: When structural separation or audit requires "ran what was planned."
- **Per-step failure rate and failure type by plan position**
  - Why: Separates systematic issues on certain step types (e.g. always failing on join) from one-off tool outages.
  - When: Multi-step execution with logged step ids.

**LLM-judge / model-judge**

- **Model-judged "did execution match the plan's intent?"**
  - Why: When logs are incomplete, a judge can compare natural-language plan to tool trace summaries.
  - When: Spot checks and dispute resolution, not as sole ground truth.

**Human-in-the-loop**

- **Human slice on plan vs execution disputes**
  - Why: Resolves cases where automation blames the wrong layer; informs whether to fix planner prompts, tool contracts, or executor error handling.
  - When: Recurring incident themes or metric disagreements.

### 1.4 Gated or supervised planning

**Quantitative**

- **Gate pass / reject / edit rates**
  - Why: Tracks how often humans or automated gates block or change plans; sudden shifts may indicate planner drift or policy mismatch.
  - When: Whenever a gate sits between plan and execution.
- **Time-to-approval (human gate)**
  - Why: Operational metric for UX and SLA design; correlates with friction and abandonment.
  - When: Human-in-the-loop gates are production-critical.
- **Post-approval execution failure rate**
  - Why: Detects "approved but not runnable" plans—contract gaps between what gates validate and what tools actually accept.
  - When: After gate rule changes or tool schema updates.

**Human-in-the-loop**

- **Review of rejected / edited plans**
  - Why: Improves gate criteria and planner prompts; catches over- or under-blocking.
  - When: Gate volume is non-trivial or quality complaints reference approval.

### 1.5 Cost, latency, and operational shape

**Quantitative**

- **Cost and latency split: planning vs execution**
  - Why: Supports tradeoffs (stronger planner, cheaper executor loop) and detects accidental double-counting or N+1 planning calls.
  - When: Heterogeneous models or APIs between phases.
- **Parallelism utilization (plan-then-execute)**
  - Why: When plans expose independent branches, measures whether execution actually parallelizes as designed or serializes unnecessarily.
  - When: Performance SLIs depend on batched execution.

### 1.6 Safety and abuse surfaces specific to planning

**Quantitative**

- **High-risk tool appearance in plans (pre-execution)**
  - Why: Even if execution is blocked later, planning should not routinely propose disallowed actions for the context.
  - When: Tools have tiered risk or tenancy rules.
- **Prompt-injection or "plan escape" success rate**
  - Why: Adversarial inputs that manipulate the plan (ignore constraints, smuggle steps) are distinct from output-only jailbreaks.
  - When: Untrusted or semi-trusted inputs drive planning.

**LLM-judge / model-judge**

- **Rationale review for planner explanations**
  - Why: When `plan_reason` or similar is logged, judges can flag inconsistencies with policy (similar spirit to routing rationale review in 3_routing_evaluation.md §1.3).
  - When: Explanations are user-visible or used for audit.

**Human-in-the-loop**

- **Review of near-miss plans**
  - Why: Catches subtle policy violations that counters miss.
  - When: Escalating assurance domains or after incidents.

---

## 2. Tradeoffs

This section is about **how we evaluate planner-executor behavior**, not about choosing patterns (for that, see 1_planner_executor_cheatsheet.md and 2_planner_executor_patterns.md).

- **Plan ground truth vs task success only**
  Perfect task outcomes can still hide **bad plans** rescued by retries or luck; plan-only scores can miss **good plans** sunk by flaky tools. Combine plan-adequacy signals with execution and end-to-end success.
- **Planner-only vs executor-only vs joint attribution**
  Metrics should support **"bad plan vs bad tool vs bad spec"** triage; otherwise teams optimize the wrong component. Shared trace schema (see minimal hooks in 1_planner_executor_cheatsheet.md) reduces debate cost.
- **Automation vs human review**
  Model judges scale for plan reasonableness and constraint checks but drift with the base model. Humans anchor definitions of acceptable plans and gate behavior for regulated flows.
- **Breadth vs focus**
  Primary candidates: plan-execution alignment, replan rate, task success by pattern, plan policy violations, plus **cost/latency split** when models differ. Add gate-specific and safety-skewed probes when stakes warrant.
- **Replay stability vs live diversity**
  Fixed replay sets catch planner regressions; live sampling catches distribution shift and edge cases. Neither alone suffices for mature systems.
- **Orthogonality to routing**
  Improving which subgraph runs the task (3_routing_evaluation.md) does not replace measuring **how** that subgraph plans and executes. Prefer stratified metrics (e.g. success and cost inside the plan-then-execute subgraph) when routing is present—see §5 in 2_planner_executor_patterns.md.
