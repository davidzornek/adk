# Agentic product foundations — introduction and contents

This collection is a **proposal** for how to **equip engineers and product SMEs** with what they need to **build good AI products**. Agent behavior is driven at least as much by experimentation—hypotheses, variants, and measurement—as by traditional software development. That is not to downplay **software engineers** as the primary builders of shippable features; it is to acknowledge that shipping reliable agents requires both **code and evaluated learning**, in one loop.

The goal is a toolkit that gives agentic work a **unified surface** (shared patterns, evaluation lenses, sketch-level code, mental models, and composability) so it **lines up naturally with an evaluation harness** maintained by Applied AI. The aim is to **remove the need to engineer around evaluation**: product teams should not spend cycles on one-off wiring just to run experiments. **Well-designed experiments** are, in practice, the **only** way to show that an agent does **what we intend—safely**. We want **consistency with that evaluation framework** to be the **easiest path** for engineers who need to **develop rapidly**.

The guiding principle here is to **make it easy to do the right thing and hard to do the wrong thing.**

This remains **internal, descriptive guidance** for **product, engineering, domain experts, and AI leadership**—something to adopt and extend together, not a single mandated architecture or a finished platform.

## How to use these documents

- **Layout.**
  - 1–5 in the table below run from this introduction through composability.
  - **Future development** — optional roadmap: YAML-driven pattern factory and variant evaluation via a harness TBD (aspirational; complements the composability guide).
  - 6–9 are pattern chapters—routing, GER, planner-executor, memory—each organized as cheatsheet → patterns → evaluation → agent components (and notebooks where linked).
  - Within a chapter, read the numbered `1_`...`4_` files in order when you are learning that area.
- **Product owners & SMEs.**
  - Start from **Working with AI — product owners & SMEs** for shared language and triage.
  - Follow into 6–9 cheatsheets when you want more depth.
  - Use **general agent evaluation** when the discussion is quality, risk, or rollout criteria.
- **Software engineers.**
  - Start from **AI vs traditional software — engineers** for misconceptions and where patterns sit in the stack.
  - Use 6–9 patterns, agent components, and usage notebooks for topology and sketch code aligned with each area.
  - Use the **composability guide** for mechanisms (subclass, inject, YAML), pattern families, and the GER-as-planner composed topology (Mermaid).
- **Applied AI.**
  - Own the **evaluation harness** and keep patterns, docs, and harness contracts aligned so agentic development stays on the **default path** into experiments—not custom side doors.
  - Anchor decisions and communications in **general agent evaluation** and the relevant **6–9 cheatsheets**.
  - Use the **composability guide** when stakeholders need ADK buy-in and a **single composed reference graph** (GER-as-planner in PE); diagrams are Mermaid in Markdown (no separate notebook).

---

## Contents at a glance

| # | Document | Audience / purpose |
|---|---|---|
| 1 | Intro and contents (this page) | Proposal; experimentation-aligned toolkit; map of the library; plug-in to Applied AI evaluation |
| 2 | Working with AI — product owners & SMEs | Non-technical framing: "laboratory vs manufacturing," triage flows, pointers into pattern cheatsheets |
| 3 | AI vs traditional software — engineers | SWE-facing comparison table, misconceptions, where routing / GER / planner-executor plug in |
| 4 | General agent evaluation | Rubric- and policy-gated agents: shared eval signals (end-to-end, phases, judges, humans) |
| 5 | Composability guide | Routing, GER, and planner-executor: **subclass vs inject vs YAML**, pros/cons, **one** composed reference topology (GER-as-planner inside planner-executor), Mermaid |
| — | Future development — pattern factory roadmap | Aspirational: YAML → same compiled graphs as Python; pass variant YAMLs to an evaluation harness TBD (not implemented in-tree) |

---

## 6 — Routing

Companion code sketch: `6_routing/routing_base_classes/` (requires `langchain-core`); demo: `5_routing_agent_usage_demo.ipynb`.

| # | Document |
|---|---|
| 1 | Routing cheatsheet |
| 2 | Routing patterns |
| 3 | Routing evaluation |
| 4 | Routing agent components |

---

## 7 — Generate–evaluate–reflect

Companion code sketch: `7_generate_evaluate_reflect/generate_evaluate_reflect_base_classes/`.

| # | Document |
|---|---|
| 1 | GER cheatsheet |
| 2 | GER patterns |
| 3 | GER evaluation |
| 4 | GER agent components |

---

## 8 — Planner–executor

Companion code sketch: `8_planner_executor/planner_executor_base_classes/`; demos and a fuller agent live under `8_planner_executor/member_insights/` and `5_planner_executor_usage_demo.ipynb`.

| # | Document |
|---|---|
| 1 | Planner–executor cheatsheet |
| 2 | Planner–executor patterns |
| 3 | Planner–executor evaluation |
| 4 | Planner–executor agent components |
| 5 | Planner–executor usage demo (notebook) |

---

## 9 — Memory

Narrative-only pattern area (no companion `*_base_classes` package in this folder yet).
