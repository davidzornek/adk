# Generate–Evaluate–Reflect cheatsheet

**Quick reference:** pattern overview and tradeoffs, runtime vs adjacent placement (e.g. AgentCore), a yes / no decision flow for when GER fits and which pattern to use, optional grounding and rubric pre-steps, and evaluation must-haves. Full narrative and examples: 2_generate_evaluate_reflect_patterns.md. General rubric/judge signals: 4_general_agent_evaluation.md. GER-specific metrics: 3_generate_evaluate_reflect_evaluation.md. Concrete components by pattern: 4_generate_evaluate_reflect_agent_components.md. Reference implementation (LangGraph, no duplicate sketches here): [sdg-agent/sdg_agent/base.py](../../../sdg-agent/sdg_agent/base.py), [sdg-agent/docs/reflection_feedback_loop.md](../../../sdg-agent/docs/reflection_feedback_loop.md).

---

## Quick maps

These tables are **compressed outcomes**. More detail below: **Pros and cons**, **Evaluation must-haves**, **Runtime vs adjacent**, and the full **Decision flow** (Part 1–2 with notes). Longer narrative: 2_generate_evaluate_reflect_patterns.md.

**Quick map — GER pattern (topology)**

| Outcome | Pattern name |
|---|---|
| Generate once → evaluate → sink; no automatic second pass | **Linear pipeline** |
| Evaluate → (reflect → generate → evaluate)* until pass or budget | **Closed-loop retry** |
| Automated GER then human / policy approval before persist or delivery | **Gated or supervised** (composes with linear or closed-loop) |

**Quick map — optional pre-phases** (often explicit nodes in graph implementations; may be folded into a single generate step)

| Outcome | Typical role |
|---|---|
| Grounding (retrieve, select, or preprocess seeds / examples) | Feeds **generator** with style- or domain-faithful context before first generate. |
| Rubric / criteria step (static load or dynamic rubric generation) | Writes task-specific criteria into state for **evaluate** (and often generate / reflect prompts). |

*Example graph with both pre-phases:* ground + rubric + generate + evaluate + ... — see the Reference implementation paths in the Quick reference above.

**Quick map — logical vs structural GER** (same product story, different engineering)

| Outcome | What it implies |
|---|---|
| Logical (one call: draft + self-critique in one prompt) | Cheaper latency; harder per-phase metrics and bounded retries. |
| Structural (separate prompts / nodes / models) | Clear traces, retry caps, different models per phase—what the patterns below assume. |

---

## Pros and cons of GER patterns

### Patterns overview

| Pattern | Brief description |
|---|---|
| Linear pipeline | Generate once, evaluate, then sink |
| Closed-loop retry | Reflect → regenerate failed items → re-evaluate until pass or budget |
| Gated / supervised | Human or policy gate before persist or delivery |

### Pros and cons table

| Pattern | Pros | Cons |
|---|---|---|
| Linear pipeline | Simple; predictable cost/latency; easy ops | No automated repair; tuning generator vs evaluator without a loop |
| Closed-loop retry | Higher yield on rubric tasks; clear per-phase telemetry | Cost/latency spikes; evaluator/reflector blind spots; needs caps |
| Gated / supervised | Compliance and audit; human judgment | Latency; gate maintenance; partial-batch semantics |

In practice, products often **blend** patterns (e.g. closed-loop up to a cap, then quarantine or human review). Composition with **routing** and **planner–executor**: 2_generate_evaluate_reflect_patterns.md §5.

---

## Evaluation must-haves

Combine GER-loop signals with **general** rubric/judge signals. Full lists: 3_generate_evaluate_reflect_evaluation.md, 4_general_agent_evaluation.md.

| Must-have | What it answers |
|---|---|
| GER yield (per request and/or per candidate) | Whether the **full loop** (including retries) produces acceptable outputs—not first-shot generation only (definitions: 3_generate_evaluate_reflect_evaluation.md §1.1). |
| Residual failure after retry budget | Ill-posed tasks vs fixable loop gaps when some requests never pass. |
| Per-attempt evaluator verdicts and rationales in traces | Backbone for debugging reflect → generate and attribution (generator vs evaluator vs reflector). |
| First-pass vs post-retry pass rate | Value added by reflection vs initial generation quality. |
| Reflection usefulness (failed → pass on next attempt) | Whether reflect output is actionable or churn. |
| Judge / rubric health (stability, calibration, safety on "passed" items) | Lenient judges and silent safety gaps—see 4_general_agent_evaluation.md. |

Add criterion-level failure counts when tuning rubrics; **human review of reflections** and **exhausted-retry failures** when closed-loop quality is critical.

---

## Runtime vs adjacent (e.g. AgentCore)

Illustrative map: what usually runs **inside** a managed agent runtime versus **outside** it. Not a platform guarantee—see the full grouped table and caveats under Typical deployment placement.

| Bundle | Usually in runtime | Usually outside / adjacent |
|---|---|---|
| Orchestration & graph | Generate / evaluate / reflect steps, conditional loop, stop policy, sink, gate clients — patterns, closed-loop, gated | — |
| Policy & retry (code) | Budget checks, failed-slot selection, in-memory GER config | — |
| Rubric / criteria | Loaded prompts; optional dynamic rubric builder in-process | Rubric **source of truth** (Git, CMS, policy service); criteria registry DBs |
| Models | API clients only | **Model serving**; fine-tuned judges |
| Grounding | Orchestration of retrieval / tool calls | Search, vector DB, document stores |
| GER state | Turn/batch payload in flight | Quarantine, audit, human-queue storage |
| Gates | Calls to gate / approval APIs | Human review UIs, workflow engines |
| Observability | Emit logs/metrics | Backends, dashboards, offline eval |

---

## ✎ Decision flow (yes / no)

Use this as a checklist, not a policy.

### Part 1 — Is a GER-style pipeline appropriate?

Answer in order.

| # | Question | If No | If Yes |
|---|---|---|---|
| 1.1 | Is quality defined by a **rubric, policy checklist, judge, or validator** (not only "vibes" or downstream manual fix)? | Stop: GER framing adds little; consider linear LLM or other patterns. | Continue to 1.2. |
| 1.2 | Would **single-shot generation** without a structured evaluate step meet product requirements for **correctness, safety, and auditability** on the traffic you care about? | GER is appropriate — go to Part 2. | You may still **evaluate once** (linear GER-lite); defer closed-loop until failures are costly enough to automate repair. |
| 1.3 (optional tie-breaker) | Do you need **separate observability or ownership** for "what was proposed" vs "why it failed" vs "what we asked next"? | Simpler single-call flows may suffice. | **Structural GER** (distinct phases) strengthens the case for explicit components and metrics (2_generate_evaluate_reflect_patterns.md §1). |

**Summary:** Prefer GER when outputs are **gated by explicit criteria** and you care about **traceability, retry control**, or **independent iteration** on generator vs evaluator vs rubric.

### Part 2 — Which GER pattern?

Assume Part 1 ended with "GER is appropriate." Start with 2.1; follow the path that matches your answer.

| # | Question | If No | If Yes |
|---|---|---|---|
| 2.1 | Will most failures be **acceptable** without an automatic second generation pass (log, quarantine, or human pick-up is enough)? | Closed-loop retry — continue to 2.2. | **Linear pipeline** (generate → evaluate → sink). Then continue to 2.3 (with or without a gate). |
| 2.2 | Do you have **budgets** (max attempts, tokens, latency) and a clear **reflection → generate contract** so retries do not run unbounded? | Define caps and contracts first; then implement closed-loop. | Implement **closed-loop retry**; instrument yield and residual failure (3_generate_evaluate_reflect_evaluation.md). Continue to 2.3. |
| 2.3 | Must a human, rules engine, or approval workflow **block persist or user delivery** even when automated evaluate passes? | Stop at automated sink (or linear / closed-loop only). | Add **gated / supervised** after automated evaluate (and after any retry loop). |

**Notes**

- **Grounding** and a dedicated rubric step are **orthogonal** to the three patterns: they sit before (or beside) generate in many implementations; see the Reference implementation paths in the Quick reference above.
- **Routing** (which subgraph runs) does not replace measuring **GER yield** inside a draft-and-QA subgraph; planner–executor may feed GER work items—see 2_generate_evaluate_reflect_patterns.md §5.
- **Logical** single-call GER (draft + critique in one prompt) is still "GER" in spirit but will not expose all components in this cheatsheet; bias toward structural GER when on-call debugging or compliance needs phase-level traces.
