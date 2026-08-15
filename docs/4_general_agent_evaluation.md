# Evaluation signals for rubric- and policy-gated agents

## Overview

This document describes evaluation signals for **LLM agents whose outputs are gated by a rubric, policy, or pass/fail judge**—whether or not they use a generate–evaluate–reflect loop, routing, or a planner–executor structure. §0 collects signals that matter for **any LLM-backed system** (single-shot chat, batch generation, or agentic flows); §§1–3 focus on gated agents and their judges. Routing-specific, **planner-executor-specific**, and **GER loop**-specific signals live in their own evaluation narratives; see 3_routing_evaluation.md, 3_planner_executor_evaluation.md, and 3_generate_evaluate_reflect_evaluation.md. Pattern context for GER: 2_generate_evaluate_reflect_patterns.md.

For each signal class we distinguish:

- **Quantitative** – automatically computed counts and aggregates.
- **LLM-judge / model-judge** – automatable qualitative checks using models as judges.
- **Human-in-the-loop** – human ratings, trace reviews, and rubric/policy refinement.

---

## ✎ 0. Signals for any LLM deployment

These apply **whether the product is agentic or not**: plain completion APIs, chat UIs, RAG, tool-augmented assistants, or full graphs. They complement—not replace—domain metrics (accuracy on labeled tasks, business KPIs, user satisfaction).

### Quantitative

- **Latency and tail latency (p50 / p95 / p99)**
  - Why: User experience and capacity planning; regressions often show up in tails before means move.
  - When: Any interactive or SLA-bound surface; after model, infra, or prompt changes.

- **Throughput and cost (tokens in/out, $ per task)**
  - Why: Ties engineering choices to budget; uncapped context or verbose outputs show up here first.
  - When: Always for production-ish workloads; essential when comparing vendors or model sizes.

- **Structured-output validity rate**
  - Why: JSON / schema / tool-argument failures break orchestration even when the natural-language answer "looks fine."
  - When: APIs, agents, or pipelines require machine-parseable shapes.

- **Golden-set regression on fixed prompts**
  - Why: Catches unintended drift in wording, format, or behavior on a small, versioned set without full re-labeling.
  - When: Every material change to model, system prompt, decoding, or retrieval stack.

- **Distributional sanity (length, stop reason, empty rate)**
  - Why: Collapsed diversity, runaway generation, or silent truncation often precede quality incidents.
  - When: New decoding defaults, context-window changes, or unusually high traffic.

### LLM-judge / model-judge

- **Criterion scores on a fixed sample (helpfulness, clarity, instruction following)**
  - Why: Cheap relative scaling across configs when human rating everything is infeasible.
  - When: You have a stable rubric and need continuous comparison across prompts or models.

- **Pairwise or ranking evaluation on challengers**
  - Why: Relative judgments are often more reliable than absolute scores for "which build is better?"
  - When: A/B tests, model upgrades, or prompt tournaments.

### Human-in-the-loop

- **Expert rating on a small golden set**
  - Why: Calibrates and model judges metrics in human judgment for the tasks you actually ship.
  - When: New task families, new models, or before raising stakes (more users, more autonomy).

- **Side-by-side or preference studies for major changes**
  - Why: Surfaces subtle regressions (tone, trust, missing caveats) that scalar scores miss.
  - When: Large prompt or UX changes, or migration between model families.

---

## 1. End-to-end outputs

### Quantitative

- **Overall acceptance rate per configuration**
  - Why: Coarse health indicator: how often the agent succeeds on its own terms under the defined pass/fail notion, across tasks, configs, and model versions.
  - When: Always when pass/fail is defined; useful as a headline metric.

- **Distributional checks vs real or target data**
  - Why: Outputs may "pass" yet be off-distribution (odd lengths, collapsed diversity, missing label modes). Simple distributional comparisons catch pathologies early.
  - When: Outputs are meant to approximate or augment a target distribution (e.g. QA pairs, classification examples, UI flows).

### LLM-judge / model-judge

- **Secondary LLM re-judging a sample of accepted outputs**
  - Why: Independent view on whether the **primary** judge is systematically over- or under-lenient; systematic disagreement on easy cases points to judge issues.
  - When: A judge gates quality at scale and you need to sanity-check its behavior.

### Human-in-the-loop

- **Human spot-checks on accepted outputs**
  - Why: Anchors automatic metrics in "would a human accept this for the intended use?"
  - When: Before routing outputs into non-toy internal workflows; periodically after prompt, task, or judge changes.

- **Task-owner review sessions**
  - Why: Surfaces nuanced expectations (tone, subtle correctness, usefulness) that generic rubrics may not encode.
  - When: New task families, substantial rubric or prompt revisions, or moving from low- to higher-stakes usage.

---

## ✎ 2. Component behavior and judges

### Quantitative

- **Evaluator stability on a small replay set**
  - Why: Pass/fail from a model judge must be reproducible enough that derived metrics are trustworthy.
  - When: Judge labels are primary quality signals or gates.

### LLM-judge / model-judge

- **Auxiliary LLM: did the evaluator apply the rubric correctly?**
  - Why: Surfaces misapplication or over-interpretation of the rubric (e.g. false rejects of acceptable outputs).
  - When: Surprising judge decisions, or new rubrics / judge prompts.

### Human-in-the-loop

- **Human alignment slice (rubric clarity and evaluator strictness)**
  - Why: Answers whether the rubric is comprehensible and whether evaluator behavior matches it.
  - When: Introducing or materially changing rubrics before treating judge scores as optimization ground truth.

- **Human-labeled micro-dataset for evaluator calibration**
  - Why: Canonical labels for measuring evaluator accuracy, bias, and drift over time.
  - When: Long-lived judges gating many examples, especially quality- or safety-sensitive contexts.

---

## 3. Safety and constraints

### Quantitative

- **Safety / constraint violation rate on accepted outputs**
  - Why: How often outputs break explicit safety or structural/semantic constraints **despite** passing the agent's own evaluation.
  - When: User-visible or downstream-consumed content; increasingly critical toward external or regulated use.

- **Disagreement rate between evaluator and safety / constraint checks**
  - Why: Highlights misalignment between rubric-conditioned judging and dedicated safety tooling; informs refinement of both.
  - When: Both a judge and separate safety or constraint mechanisms are in play.

- **Structural constraint adherence**
  - Why: Verifies formats and schemas (required fields, forbidden fields, disallowed sections) for downstream systems.
  - When: Outputs feed pipelines that assume specific structure.

### LLM-judge / model-judge

- **LLM safety / constraint judge on samples**
  - Why: Nuanced violations and richer labels (category, severity) when rules alone are insufficient.
  - When: Complex or domain-specific safety/constraints.

- **LLM judge on adversarial or edge-case prompts**
  - Why: Stress-tests whether failures are acceptable or dangerous.
  - When: Higher-stakes deployment prep or probing sharp failure modes.

- **LLM checks for soft constraints (tone, subtle behavior rules)**
  - Why: Structured assessments for brand- or UX-sensitive rules beyond bare correctness.
  - When: User-facing or brand-sensitive tasks.

### Human-in-the-loop

- **Human policy / safety review on samples**
  - Why: Anchors policy in human judgment; finds where rubrics and tools miss real policy intent.
  - When: Before real user exposure, or in compliance- or reputation-sensitive domains.

- **Human review of adversarial suite outputs**
  - Why: Ensures tricky inputs yield acceptable outcomes or documented limitations.
  - When: Designing or updating adversarial suites; regression checks for new agent versions.

- **Constraint and rubric refinement sessions**
  - Why: Uses real failures and near-misses to improve how constraints are expressed to models.
  - When: Ongoing, especially after repeated violation patterns.
