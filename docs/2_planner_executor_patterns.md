# Product Foundations: Planner–Executor

## 1. Context and scope

This document sketches how planner-executor decomposition could appear in our products and how common implementation patterns work, without committing to a specific architecture or vendor. It is internal, descriptive, and written as **reference guidance for senior AI leadership** when aligning with product, engineering, and risk partners on architecture and delivery—alongside the sibling `[routing](../routing/)` foundations.

**Quick reference:** 1_planner_executor_cheatsheet.md. **Metrics, tradeoffs, and evaluation:** 3_planner_executor_evaluation.md. **Concrete components per pattern (nodes, state, gates):** 4_planner_executor_agent_components.md.

We focus here on splitting **what to do next** (planning: goals, steps, tool choices, ordering) from **doing it** (execution: invoking tools, handling errors, updating state). That split can be logical (one model wearing two hats), structural (two prompts or two subgraphs), or organizational (two teams owning different artifacts).

### Logical, structural, and organizational splits (and why they matter)

The **same** product narrative—"we have a planner and an executor"—can hide very different engineering realities:

- **Logical** – Separation lives mainly in prompts, conventions, or in-context roles; one service or graph node may still run both. Patterns in §4 still apply as *conceptual phases* even when not separate deployables.
- **Structural** – Separation is visible in code or graphs: distinct nodes, prompts, or packages, with an explicit handoff (usually a **plan artifact** or state fields). That unlocks different graph shapes (e.g., batched plan then execute, explicit replan edges) and clearer tracing.
- **Organizational** – Different groups own **schemas** (plan format, tool manifests), **release cadence**, or **on-call** for "bad plans" vs "failed tools." The boundary becomes a **contract**: versioning, compatibility, review gates, and eval ownership follow.

**Choosing among these is not cosmetic:** it drives which patterns in this document are easy or painful—whether execution can be gated on plans, how incidents are attributed, how changes are tested and released, and whether planner and executor surfaces can evolve on different cadences. The implementation patterns below are written in **structural** terms; **explicit leadership sponsorship** is what turns logical vs structural vs organizational intent into durable ownership, contracts, and delivery that match how the product actually runs.

---

## 2. What we mean by planner–executor

**Planning** is the work of producing or updating a representation of intended work: subgoals, ordered or parallel steps, tool names, parameters, success criteria, or stop conditions. Plans may be explicit (a list the user sees) or implicit (scratchpad only).

**Execution** is the work of carrying steps out: calling APIs, running tools, writing to state, surfacing partial results, and detecting failure or completion.

**Planner–executor** is the pattern where these concerns are **separated enough** to reason about, test, and govern independently—even if a single LLM call sometimes does both for latency or simplicity.

Typical motivations:

- **Safety and policy** – approve or constrain plans before expensive or irreversible actions.
- **Observability** – log "intended steps" separately from "what actually ran."
- **Cost and latency** – use a smaller or faster model for execution-heavy loops and a stronger model only for replanning.
- **Iteration** – replan after tool errors, partial observability, or user mid-course corrections.

This is orthogonal to **routing** (which capability owns the turn): a routed subgraph can itself be implemented as planner-executor, and a planner can output route-like labels (e.g., which specialist tool to use next).

---

## 3. Example scenario: data analysis to answer a question

To ground the discussion, consider a toy product flow:

- **User ask:** "Did refund rates spike last month for enterprise customers, and which segments drove the change?"
- **Planner** might emit: (1) confirm which tables or exports hold refunds and customer tier, (2) define the metric and time window, (3) aggregate at the right grain and slice by segment, (4) sanity-check counts and nulls, (5) summarize conclusions and caveats.
- **Executor** runs query, notebook, or BI tools, checks for missing inputs or ambiguous schema, and returns observations after each step.

The example is deliberately simple; it illustrates **decomposed reasoning**, **tool grounding**, and **replanning** when a step fails (e.g., missing table, permission error, empty cohort, query timeout).

---

## 4. Planner–executor implementation patterns

We distinguish three patterns that often compose in real systems. For a step-through checklist, see **Decision flow** in 1_planner_executor_cheatsheet.md.

1. Interleaved plan-act (tight loop)
2. Plan-then-execute (batched plan artifact)
3. Gated or supervised planning

### 4.1 Interleaved plan-act (tight loop)

In this shape, planning and execution **alternate** frequently—sometimes every tool call. The agent picks one next action (or a very short horizon), executes it, observes the result, then plans again.

At the graph level, this often looks like a cycle:

```
plan_step → execute_step → observe → (replan or finish)
```

**Pros**
- Adapts quickly to tool errors and surprising observations.
- Does not require a full upfront plan; works well under partial information.
- Familiar to ReAct-style and many single-agent loop designs.

**Cons**
- Harder to show users a stable "whole plan" before work starts.
- Can thrash or repeat work if the planner lacks memory of prior attempts.
- Observability must deliberately capture "why this step" each iteration.

### 4.2 Plan-then-execute (batched plan artifact)

Here the system first produces a **plan artifact** (structured steps, DAG, checklist) and then an **executor** walks it—sequentially, in parallel where safe, or with explicit dependencies. Replanning may be a separate trigger (failure, timeout, user edit) rather than every step.

At the graph level, this can look like:

```
plan_node → [optional validate] → execute_steps → (merge or synthesize) → END
```
- With a conditional edge back to `plan_node` on replan conditions.

**Pros**
- Clear user-facing narrative: "here is what I will do."
- Easier to apply static checks (policy, allowlists) on the full plan.
- Supports parallel execution when the plan exposes independent branches.

**Cons**
- Upfront plans go stale when the world changes mid-run.
- Requires explicit replan policy and merge logic.
- More engineering for plan schema versioning and partial execution.

### 4.3 Gated or supervised planning

In high-stakes or regulated settings, **a human, rules engine, or second model may approve, edit, or reject the plan** (or each batch of steps) before execution proceeds. The executor runs only authorized steps.

This composes with 4.1 or 4.2: the gate sits between plan output and tool invocation.

**Pros**
- Strong alignment with human oversight and audit requirements.
- Reduces catastrophic tool misuse from a single bad plan.
- Clear accountability boundary: "approved plan" vs "executed actions."

**Cons**
- Latency and UX friction when humans are in the loop.
- Automation of the gate (second model) reintroduces evaluation and drift concerns.
- Requires clear semantics for partial approval and plan diffs.

---

## 5. Composition and relationship to routing

- Routing answers which agent or subgraph handles the request; **planner-executor** answers *how* that subgraph structures goal decomposition and tool use.
- A router might send "complex research" to a subgraph that is **plan-then-execute**, and "simple FAQ" to a single-shot responder with no separate planner.
- Hybrid products often use **interleaved** loops internally while still surfacing a **summary plan** to the user for transparency (plan artifact updated lazily).
- A planner can include an internal **router or route-like dispatch** (specialist, template, policy bundle) before step details are fixed; that is **nested composition** and does not contradict planner-executor as long as dispatch is part of intent before committed execution (reopened only on replan).

---

## 6. Pros and cons at a glance

| Pattern | Brief description | Strengths | Risks |
|---|---|---|---|
| Interleaved plan-act | Short horizon; plan and execute alternate in a loop | Fast adaptation; minimal upfront commitment | Weaker upfront visibility; possible thrashing |
| Plan-then-execute | Full or multi-step plan artifact before bulk execution | Auditable intent; parallelization; batch policy checks | Stale plans; replan/merge complexity |
| Gated / supervised planning | Approval or policy gate before execution | Safety and compliance; clear audit trail | Latency; gate quality and maintenance |

In practice, we expect non-trivial products to **blend** these patterns: e.g., batched plan for user display with interleaved replanning on failure, plus gates only for sensitive tools or environments.
