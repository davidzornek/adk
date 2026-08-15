# Product Foundations: Generate–Evaluate–Reflect

## 1. Context and scope

This document sketches how **generate–evaluate–reflect (GER)** pipelines could appear in our products and how common implementation patterns work, without committing to a specific architecture or vendor. It is internal, descriptive, and written as **reference guidance for senior AI leadership** when aligning with product, engineering, and risk partners on architecture and delivery—alongside the sibling `routing` and `planner_executor` foundations.

**Quick reference:** 1_generate_evaluate_reflect_cheatsheet.md. **Metrics, tradeoffs, and evaluation:** general rubric/policy signals 4_general_agent_evaluation.md; GER-specific 3_generate_evaluate_reflect_evaluation.md. **Concrete components by pattern (nodes, state, gates):** 4_generate_evaluate_reflect_agent_components.md.

We focus here on systems that **produce candidate outputs, check them against criteria**, and optionally **repair** them using structured feedback—not on a single domain (e.g., synthetic data only). GER is a natural fit whenever quality is defined by a rubric, policy checklist, or judge, and when failed attempts should drive another generation pass rather than failing the whole run.

### Logical, structural, and organizational splits (and why they matter)

The same product narrative—"we generate, then evaluate, then reflect"—can hide different engineering realities:

- **Logical** – Phases live in one prompt or one model call (e.g., "think step by step: draft, self-critique, revise") without separate services or graph nodes. Patterns in §4 still describe conceptual phases and failure modes.
- **Structural** – Phases are visible in code or graphs: distinct prompts, models, or nodes with explicit state (pass/fail, reasoning, feedback text). That unlocks conditional retries, per-phase observability, and different models or temperatures per step.
- **Organizational** – Different groups own **rubric or policy definitions**, **evaluator prompts or judges**, or **release cadence** for generation vs evaluation. The boundary becomes a **contract**: what "pass" means, how feedback is formatted, and who approves changes.

**Choosing among these is not cosmetic:** it drives whether retries are bounded and auditable, how incidents are attributed ("bad generation" vs "harsh evaluator" vs "unhelpful reflection"), and whether you can ship rubric changes independently from generator changes. The patterns below are written in **structural** terms; leadership clarity on ownership and contracts determines whether GER remains a slogan or a governable system.

---

## 2. What we mean by generate–evaluate–reflect

**Generate** is the work of producing candidate artifacts: text, structured records, plans, tool arguments, or batches of examples. Inputs typically include a task definition, constraints, and optionally **grounding** (retrieved passages, seed examples, or style references).

**Evaluate** is the work of scoring or gating those artifacts against explicit or learned criteria: rubrics, safety rules, format validators, LLM-as-judge, or hybrid checks. Outputs usually include pass/fail (or scores) and **reasoning** that downstream steps can consume.

**Reflect** is the work of turning evaluation signal into **actionable feedback** for the generator: not merely logging failure, but producing guidance the next generate step can use (what to fix, what to preserve, what to avoid).

**Generate–evaluate–reflect** is the pattern where these concerns are **separated enough** to test, observe, and iterate independently—even if a single call sometimes collapses "draft and self-critique" for latency.

Typical motivations:

- **Quality and alignment** – enforce rubrics and policies before persistence or user-facing release.
- **Observability** – separate traces for "what was proposed" vs "why it failed" vs "what we asked for next."
- **Cost and capability** – use a smaller or faster model for bulk generation and a stronger or more conservative model for evaluation or reflection.
- **Controlled repair** – bounded retry loops instead of open-ended chat when the product needs predictable termination.

This is orthogonal to **routing** (which capability owns the turn) and to **planner–executor** (how work is decomposed and executed): a routed subgraph can be a GER pipeline; a planner can emit work items that a GER subgraph then produces and validates.

---

## 3. Example scenario: draft FAQ answers under a style rubric

To ground the discussion, consider a toy internal flow:

- **Task:** Given support ticket snippets, draft short FAQ-style answers.
- **Generate** produces three candidate answers per ticket.
- **Evaluate** checks each against a rubric: correct product facts, no promises we cannot keep, reading level, and tone.
- **Reflect** runs only for failures, producing bullet feedback tied to the evaluator's reasoning (e.g., "remove warranty language; cite only public docs").

---

## 4. Generate–evaluate–reflect implementation patterns

We distinguish three patterns that often compose in real systems:

1. Linear pipeline (no retry)
2. Closed-loop retry (reflect → generate → evaluate)
3. Gated or supervised generation

### 4.1 Linear pipeline (no retry)

The system runs **generate → evaluate → sink** (write, return, or hand off). There is no automatic second generation pass; failures may be logged, flagged for humans, or handled elsewhere.

At the graph level, this often looks like:

```
generate → evaluate → write_or_return → END
```

**Pros**
- Lowest latency and cost when retries are rare or unnecessary.
- Simplest operations story: no cycles, clear termination.
- Easy to reason about compliance when every artifact is either accepted or explicitly rejected once.

**Cons**
- Leaves quality on the table when many failures are **repairable** with short feedback.
- Pass rate becomes a blunt instrument unless paired with human or offline review.
- Evaluator strictness and generator capability must be tuned together without an automated repair path.

### 4.2 Closed-loop retry

After evaluate, a **conditional** step decides whether to continue: if some items failed and **budget** (e.g., max reflections per item, global token cap) allows, the flow runs reflect to produce feedback, then **generate** again (often only for failed slots), then **evaluate** again. The cycle repeats until all pass, budget is exhausted, or a stop policy fires.

At the graph level, this often looks like:

```
generate → evaluate → (reflect → generate → evaluate)* → write_or_return → END
```

**Pros**
- Improves yield on rubric-governed tasks without manual intervention for every failure.
- Separates "what failed" (evaluate) from "how to fix it" (reflect), which aids debugging and prompt iteration.
- Supports **per-item** retry budgets, which is important when batch size is greater than one.

**Cons**
- Latency and cost scale with worst-case retries; needs caps and monitoring.
- Evaluator–generator loops can reinforce biases (evaluator and reflector share blind spots) or oscillate if feedback is vague.
- Requires clear rules for **partial success** (e.g., write only passing rows, drop or quarantine the rest).

### 4.3 Gated or supervised generation

In high-stakes or regulated settings, **humans, rules engines, or approval workflows** may block persistence or user delivery until artifacts pass evaluation—or may **edit** criteria or outputs before another generate pass. Automated reflect/generate cycles may still exist, but only **authorized** states proceed.

This composes with 4.1 or 4.2: gates typically sit **after** evaluate (or after a successful retry loop) and before **write** or downstream tools.

**Pros**
- Strong fit for audit, policy sign-off, and "human as final judge" products.
- Reduces risk of shipping automated repairs that violate policy.
- Clear accountability: approved artifact vs raw model output.

**Cons**
- Latency and staffing cost when humans are mandatory.
- Automated "gates" (second model) reintroduce evaluation and drift concerns, similar to LLM-as-judge elsewhere.
- Needs semantics for **partial batches** and versioning when humans edit rubrics or examples.

---

## Where criteria and rubrics live

Criteria can be **static** (fixed prompts and checklists), **dynamic** (a dedicated step that writes a rubric or checklist into state from task context), or **external** (policy service, feature flags, regulated rule sets). The GER pattern does not mandate one choice; it requires that **evaluate** has an auditable notion of "pass" and that **reflect** receives enough signal to improve the next **generate** pass when retries are used.

---

## 5. Composition with routing and planner–executor

**Worked example (topology + sketch base classes):** Composability guide walks GER as planner inside planner–executor (subclass / inject / YAML) with Mermaid; runnable stubs live in pattern demos under `6_routing/`, `7_generate_evaluate_reflect/`, and `8_planner_executor/`.

- **Routing** answers *which* agent or subgraph runs; a subgraph may be a full GER pipeline (e.g., "draft + QA" specialist).
- **Planner–executor** answers *how* work is structured into steps and tools; a planner might emit a list of content tasks that each flow through a **linear** or **retry** GER subgraph.
- Hybrid products often use **linear GER** for low-risk paths and **closed-loop retry** only when evaluation fails or when the user opts into "improve this answer."

---

## 6. Pros and cons at a glance

| Pattern | Brief description | Strengths | Risks |
|---|---|---|---|
| Linear pipeline | Generate once, evaluate, then sink | Simple; predictable cost/latency; easy ops | No automated repair; tuning generator vs evaluator without a loop |
| Closed-loop retry | Reflect → regenerate failed items → re-evaluate until pass or budget | Higher yield on rubric tasks; clear per-phase telemetry | Cost/latency spikes; evaluator/reflector blind spots; needs caps |
| Gated / supervised | Human or policy gate before persist or delivery | Compliance and audit; human judgment | Latency; gate maintenance; partial-batch semantics |

In practice, we expect non-trivial products to **blend** these patterns: e.g., automated retry up to a cap, then quarantine or human review for remaining failures.

---

## 7. Concrete reference implementation (optional)

For engineers who want a LangGraph-shaped illustration of a GER base class and a closed-loop retry after evaluate, the open-source package in this repository under `sdg-agent/sdg_agent/base.py` (`GenerateEvaluateReflectAgent`) and companion docs (for example `sdg-agent/docs/reflection_feedback_loop.md`) show one instantiation. The product foundations narrative above is intentionally broader than that package's domain.
