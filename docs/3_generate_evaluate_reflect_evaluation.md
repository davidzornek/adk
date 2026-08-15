# Evaluation Paradigm for Generate–Evaluate–Reflect (GER)

## Overview

This document describes the evaluation paradigm for **generate–evaluate–reflect (GER)** agents: pipelines that **generate** candidate outputs, **evaluate** them under a rubric or policy, optionally **reflect** to produce feedback, and **retry** up to a budget before returning final items. It covers **GER-specific** signals only—yield, retries, reflection dynamics, and loop-level triage. Signals that apply to any **rubric- or policy-gated** agent (acceptance rates, judge stability, safety on accepted outputs) are in 4_general_agent_evaluation.md. Routing and **planner–executor** concerns are evaluated in their own documents; see 3_routing_evaluation.md, 3_planner_executor_evaluation.md, and pattern context in 2_generate_evaluate_reflect_patterns.md. **Concrete components** (state, nodes, gates, deployment): 4_generate_evaluate_reflect_agent_components.md.

For each signal class we distinguish:

- **Quantitative** – automatically computed counts and aggregates.
- **LLM-judge / model-judge** – automatable qualitative checks using models as judges.
- **Human-in-the-loop** – human ratings, trace reviews, and rubric/policy refinement.

---

## 1. GER-specific signals

These assume a GER architecture: generate candidates, evaluate under a rubric, optionally reflect using evaluator signal, retry until pass, budget exhaustion, or stop policy.

### 1.1 End-to-end outcomes (GER-specific)

**Quantitative**

- **Acceptance rate as GER yield**
  - Why: "Accepted" means survived the full loop (possibly after retries), so yield reflects **loop effectiveness**, not first-shot generation alone.
  - Definitions (per request `i`): `N_req` = number of GER requests; `A_i` = number of **accepted** items for request `i`; `C_i` = **total** candidate items generated for request `i` across all attempts.
    - Per request: `GER_accept_rate_per_request` = (number of requests with `A_i >= 1`) / `N_req`.
    - Per candidate: `GER_accept_rate_per_candidate` = (sum of `A_i` over `i`) / (sum of `C_i` over `i`).
  - When: Always for GER agents; especially when comparing reflection strategies, rubric designs, or retry limits.

- **Residual failure rate after the retry limit**
  - Why: Fraction of requests with **no** acceptable outputs after exhausting reflections—separates ill-posed cases from fixable loop gaps.
  - When: Deciding whether to change loop configuration vs accept unsatisfied demand.

**LLM-judge / model-judge**

- **Per-attempt evaluator verdicts and rationales (in traces)**
  - Why: Evaluation drives retries and acceptance; per-attempt pass/fail plus rationale is the backbone of GER debugging.
  - When: Always log for closed-loop systems; essential for analysis.

### 1.2 Component behavior (GER-specific)

**Quantitative**

- **First-pass vs post-retry pass fractions (by rubric variant)**
  - Why: Separates initial generation quality from value added by reflection and retries; shows rubric/config effects on the balance.
  - When: Tuning reflection prompts, rubric design, or retry budget tradeoffs.

- **Frequency of each rubric criterion as failure reason**
  - Why: Shows which criteria most often block acceptance—candidates for rewording, re-emphasis, or better grounding.
  - When: Iterating rubric content or diagnosing systematic generator gaps.

- **Reflection usefulness: fraction of failed items that pass on the next attempt**
  - Why: Measures whether reflection is followed by a **successful** fix vs ineffective churn.
  - When: Editing reflection prompts, mapping evaluator rationales to reflect instructions, or questioning retry value.

- **Attempts-to-pass distribution and fraction never passing**
  - Why: Characterizes loop dynamics (quick successes vs long tails vs ultimate failure); informs retry caps and waste detection.
  - When: Changing max retries, reflection quality, or evaluator strictness.

- **Average reflections per accepted item**
  - Why: Compact summary of how much iterative refinement typically precedes success.
  - When: Comparing GER variants or tracking drift over time.

- **Grounding quality proxies vs acceptance rate**
  - Why: Tests whether stronger or more representative grounding (seeds, context) improves GER success as expected.
  - When: Experimenting with grounding strategies or when performance varies by data source or seed quality.

**LLM-judge / model-judge**

- **Grounding consistency ("on-style vs seeds?")**
  - Why: Detects rubric-compliant outputs that are still off-style or unfaithful to references.
  - When: Style or faithfulness to seeds matters, or outputs feel "compliant but wrong."

- **Reflections classified as actionable vs not actionable**
  - Why: Distinguishes concrete, targeted feedback from rubric repetition or vague advice—directly tied to loop effectiveness.
  - When: Reflection seems to move pass rates or quality little.

- **Retry traces labeled improved, unchanged, or worse**
  - Why: Summarizes whether reflect-retry tends to improve outputs or oscillate / regress.
  - When: Investigating stubborn errors, looping behavior, or new reflection strategies.

**Human-in-the-loop**

- **Human review of reflections**
  - Why: Rapid check that reflections are specific, tied to evaluator feedback, and actionable for the next generate step.
  - When: After reflection prompt changes or when reflection usefulness metrics are low.

- **Human review of exhausted-retry failures**
  - Why: Separates impossible or ill-posed tasks from cases fixable via grounding, rubric, or prompt changes.
  - When: Residual failure rate is sizeable and you must choose loop changes vs accepting a failure floor.

---

## 2. Tradeoffs

This section is about **how we evaluate GER behavior**, not about choosing implementation patterns (for that, see 2_generate_evaluate_reflect_patterns.md). Judge quality, leniency, and safety on accepted outputs are discussed alongside general gated-agent signals in 4_general_agent_evaluation.md.

- **Judge ground truth vs end-to-end acceptance**
  High acceptance can mask a **lenient** judge; strict judges can tank yield while improving true quality. Combine acceptance rates with **calibration** slices, secondary judges, and human anchors.

- **Generator vs evaluator vs reflector attribution**
  Metrics should support triage among **bad generation**, **harsh or miscalibrated evaluation**, and **unhelpful reflection**; otherwise teams tune the wrong component. Per-attempt traces and criterion-level failure counts help.

- **GER yield vs cost and latency**
  Per-candidate acceptance and average reflections per success interact with token and wall-clock budgets. Compare variants under **fixed budget** when product constraints bind.

- **Automation vs human review**
  Model judges and LLM meta-checks scale but drift with base models. Humans remain essential for rubric alignment, reflection quality, and exhausted-retry triage on high-stakes traffic.

- **Breadth vs focus**
  Instrument the smallest set that answers current failure hypotheses; add signals when traces show blind spots (e.g. oscillating retries, judge-safety disagreement).

- **Replay stability vs live diversity**
  Replay sets catch judge and generator regressions; live sampling catches shift and long-tail behavior. Neither alone suffices for mature systems.

- **Orthogonality to routing and planner–executor**
  Improving which subgraph runs or how plans execute does not replace measuring **GER yield and loop dynamics** inside a draft-and-QA or SDG-style subgraph. Stratify GER metrics by route or plan type when those upstream choices materially change tasks or rubrics.
