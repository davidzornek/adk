# AI Development vs. Traditional Software Development

*Internal reference for software engineers working on or alongside AI-powered systems.*

> **Scope:** LLM-backed behavior **plus** deterministic scaffolding in the stack (tools, routing, parsers, stores, eval harnesses)—not the idea that real systems are "just the model."

**On this page:** Core dimensions (Part 1, Part 2) · Misconceptions · Axioms · General agent evaluation · Where SWEs plug in (Routing, Planner-executor, GER)

---

## Core Dimension Comparison

### Part 1 — Single-call LLMs with monolithic prompts

| Dimension | Traditional Software | Single-call LLM / LLM API |
|---|---|---|
| Core artifact | Deterministic logic encoded in source code | A probability distribution over outputs, shaped by a model, prompt, and data |
| Correctness | Binary — the output is right or wrong by spec | Distributional — outputs are correct at some rate across a population of inputs |
| Debugging | Trace execution, inspect state, find the bug | Characterize failure modes statistically; often there's no one line to fix in the **model** itself—while scaffolding (tool contracts, routing, parsing) can still have ordinary bugs |
| Testing signal | Unit/integration tests — deterministic pass/fail | Evals — statistical coverage across a sample distribution, often with human or model judges |
| Iteration loop | Write code → run tests → deterministic signal | Change prompt/model/data → re-run eval suite → interpret distribution shift |
| Prompts vs. code | Code is deterministic logic — inspect to understand | Prompts, schemas, and examples are inspectable and are **part of the program**—but behavior is non-deterministic and interaction-dependent; they are **not** sufficient to reason about outcomes without evals |
| Regression | A code change breaks a known behavior — immediately detectable | Model or prompt updates shift the output distribution silently — requires instrumented monitoring |
| Performance | Latency, throughput, memory — measured precisely | Task accuracy, hallucination rate, refusal rate, distribution drift — measured statistically |
| Failure mode | Hard errors — exceptions, crashes, wrong output | Soft errors — plausible-sounding wrong outputs, subtle bias, inconsistency |
| Spec / source of truth | Requirements doc, acceptance criteria, tests | Eval harness — treat the eval set as the **closest thing to a spec**; prompts and models iterate against it (not purely "derived from" it in a strict sense). |
| Versioning | Code versions are fully reproducible | Model versions + prompt versions + data versions — any can shift behavior independently |
| Benchmarks | Performance benchmarks generalize well within the problem class | Public benchmarks (MMLU, etc.) are weakly predictive of task-specific behavior — always eval on your actual distribution |
| Deployment risk | Known blast radius — what broke is traceable | Unknown blast radius — output distribution changes may not surface until traffic analysis |
| Reproducibility | Given the same input, output is identical | Non-deterministic by default (temperature > 0); even at temperature 0, the serving stack can introduce run-to-run variance unless the provider explicitly guarantees deterministic decoding (see Part 2 intro) |
| Ownership | Engineers own the logic directly | Engineers own the scaffolding and eval coverage; model behavior is partially external |

### Part 2 — What agentic systems add on top

Agentic systems still use the same underlying LLM behavior as in the single-call framing above, but the **unit of concern** shifts from a single output to a **trajectory**: a sequence of tool calls, decisions, and state transitions over time. Even at **temperature 0**, serving stacks can still introduce **run-to-run variance** (provider options, batching, nondeterministic kernels)—don't assume bit-identical replay without explicit guarantees.

| Dimension | Single-call LLM | Agentic / multi-step systems |
|---|---|---|
| Unit of work | One request → one response | Trajectory with N steps (plan, tools, observations, replans) |
| Correctness | Rate over individual outputs | Rate over full trajectories (does the sequence of actions achieve the goal safely?) |
| Failure surface | Wrong or low-quality answer | Wrong actions, wrong tools, wrong order, wrong stopping point — even if the final answer looks plausible |
| Debugging | Sample I/O pairs, analyze prompt/model | Replay full trajectories, separate planning vs execution vs routing failures |
| Testing signal | Eval suite over single calls | Trajectory evals in sandboxed environments; trajectory regression suites |
| State handling | Stateless or simple request context | State spans **multiple steps within a run** (and sometimes across sessions); context window limits, summarization, and drift become failure modes |
| Side effects | Often fewer writes and fewer irreversible effects than tool-using agents (retrieval/DB and other I/O are still common) | Real side effects via tools (writes, deletions, sends, external API calls) |
| Spec / source of truth | Eval harness for single-turn behavior | Specs for allowed trajectories, tools, and permissions; HITL placement and reversibility as first-class design |
| Observability | Input/output logging and quality sampling | Step-level logs: plan, chosen tools, parameters, responses, gate decisions, halts |
| Ownership | Engineers own the call site and prompt | Engineers own the scaffold, tools, routing, planner-executor or GER topology, and eval coverage; model still owns the path within the scaffold |

---

## Common SWE Misconceptions

### For single-call LLM systems

- **Prompts are like code.**
  Prompts don't execute deterministically. Tweaking wording is not debugging — it's adjusting a hyperparameter with no guarantee of directionality. You can make a prompt "worse" while it looks more precise. Contrast with the **Prompts vs. code** row in the single-call comparison table.

- **It worked on my examples, ship it.**
  A handful of manual tests is not an eval. AI systems fail on the distribution tail — the inputs you didn't think to test. Coverage across realistic input distributions is the bar, not anecdotal spot-checks. See General agent evaluation and **Your eval set is your real test suite** in single-call axioms.

- **Benchmark scores transfer.**
  MMLU, HumanEval, etc. measure general capabilities under controlled conditions. Your task, your data, your users — these have different failure modes. Leaderboard rank is a weak signal for production performance. See **Benchmarks** in the single-call comparison table.

- **Model upgrades are free wins.**
  Newer models can regress on specific behaviors even while improving on averages. Every model change requires eval re-runs. There are no free upgrades without regression testing. See **Model changes are breaking changes until proven otherwise** in single-call axioms.

- **Instability means a prompting problem.**
  If behavior is inconsistent across model families or versions, the first hypothesis should be insufficient eval coverage — not a prompting deficiency. Chasing prompt fixes for systemic instability is a dead end. See also **The eval harness is the primary artifact** in single-call axioms.

- **Failure modes look like errors.**
  The orchestration and tools can throw like normal software—but **model outputs** often look fine while being wrong: hallucinations, hedging, drift, subtle misreads. Exception-only monitoring misses most quality failures; add semantic or rubric-based signals. In agentic stacks, **Failure surface** and **Observability** in the agentic comparison table spell out how this gets worse.

### Additional misconceptions for agentic systems

- **"It's just more of the same LLM behavior."**
  Agentic systems change the failure surface: the primary risk is now **wrong actions over time**, not just wrong answers. A trajectory that "eventually" gets the right answer via unsafe steps is still a failure. See **Failure surface** and **Correctness** in the agentic comparison table.

- **Evaluating the final output is enough.**
  A correct result via a bad trajectory (unsafe tools, wrong order, ignored gates) is a system failure: you still have to **score the path**, not only the destination. That does not mean product should ignore the answer—the final outcome is often still the headline KPI—but path quality drives **safety, cost, and auditability**, and can fail even when the last message looks fine. See General agent evaluation and **Testing signal** and **Correctness** in the agentic comparison table.

- **Constraints in the prompt are sufficient.**
  "Don't delete anything" in a system prompt is a soft constraint. In agentic systems, allowed tools, scopes, and permissions must be enforced in code and configuration, not only in prompts. See **Architectural constraints beat prompt constraints** in additional axioms for agentic systems.

- **Letting the agent improvise is a feature.**
  Improvisation on unexpected or ambiguous state is how blast radius grows. For most production systems, "halt and surface" on ambiguity is a feature, not a limitation.

- **Human review is an afterthought.**
  In agentic systems, where you place human-in-the-loop (pre-plan, per step, on exceptions, or sampling-based) is part of the architecture, not something you bolt on later. See **Spec / source of truth** in the agentic comparison table.

---

## Operating Axioms

### For single-call LLM systems

- **The eval harness is the primary artifact.**
  Prompts, models, and chains should **iterate against** it—treat the eval set as the closest thing to a spec, not something you paste prompts into after the fact. Ground in General agent evaluation; same idea as **Spec / source of truth** in the single-call comparison table.

- **Correctness is a rate, not a state.**
  A system that's right 94% of the time requires different engineering intuitions than one that's either right or broken.

- **Your eval set is your real test suite.**
  It must cover the actual input distribution — edge cases, adversarial inputs, underrepresented cases — not just the happy path. See General agent evaluation.

- **Model changes are breaking changes until proven otherwise.**
  Run evals before promoting any model version to production.

- **Observability is not optional.**
  Log inputs, outputs, and latency. Sample and review. Silent regression is the default failure mode of unmonitored AI systems.

- **Prompt engineering is not a substitute for system design.**
  Retrieval strategy, context management, chunking, routing, and output parsing are engineering problems — not prompt problems.

### Additional axioms for agentic systems

- **Trajectories, not calls, are the unit of behavior.**
  Specs, evals, and logs must treat "sequence of actions + outcome" as the thing you care about, not just the last model response. Matches the agentic comparison table framing (Unit of work, Correctness). For how to evaluate multi-step behavior, see General agent evaluation.

- **Reversibility is a design constraint, not a nice-to-have.**
  Prefer read before write, soft delete before hard delete, draft before send. Irreversible actions require additional safeguards and often different HITL placement.

- **Autonomy and blast radius must be proportional to demonstrated reliability.**
  Start with narrow permissions and conservative oversight. Expand autonomy only after evals and production metrics show stable behavior over time.

- **Architectural constraints beat prompt constraints.**
  Allowed tools, scopes, and rate limits belong in scaffolding and configuration — prompts can reinforce intent but cannot guarantee safety.

- **Halt-on-ambiguity is the default, not the fallback.**
  When the agent encounters ambiguous instructions, unexpected state, or failed tools, the safe default is to stop and surface the issue, not to guess and proceed.

- **Pattern choice (routing, planner-executor, GER) is part of the design, not an implementation detail.**
  Which pattern you use changes eval design, logging needs, and how humans stay in the loop. Pattern selection should be explicit in design docs, not implicit in code. See Routing, Planner–executor, and GER below. Shared eval methodology: General agent evaluation. Repo entry points: routing cheatsheet, planner-executor cheatsheet, GER cheatsheet.

---

## From Single-Call to Agentic: Where SWEs Plug In

This section is intentionally high-level. It extends the Core Dimension Comparison above—especially Part 2—into concrete architecture surfaces. Evaluation methodology that applies across patterns is in General agent evaluation. For **GER nested as the planner** inside planner-executor—and how an ADK might expose that graph via subclass vs inject vs YAML—see Composability guide. Each subsection's **What to look up** lists that area's cheatsheet (1), patterns (2), and agent components (4) pages.

### Routing (which subgraph handles the work)

- **What it is.**
  Deciding *where* a request goes — which sub-agent, tool stack, or model tier handles a given input.

- **What changes for SWEs vs single-call.**
  - You now own routing policies and their implementation (rules, classifier-backed routers, graph edges).
  - You need evals and logs for "was this routed to the right place?" in addition to "did the handler do the right thing?" (see General agent evaluation).

- **What to look up.**
  - Routing cheatsheet — graph shapes, rule-based vs classifier-based routing, eval must-haves, runtime vs adjacent placement.
  - Patterns, agent components.

### Planner–executor (separating intent from action)

- **What it is.**
  Splitting "what we plan to do" (plan) from "what we actually do" (execution), often with explicit plan artifacts and replan logic.

- **What changes for SWEs vs single-call.**
  - You are now responsible for storing and logging plans and executed steps separately.
  - You must reason about pattern choice (interleaved, plan-then-execute, gated) and how it affects evals, reversibility, and HITL (see General agent evaluation).

- **What to look up.**
  - Planner–executor cheatsheet — split types (logical, structural, organizational), pattern choice, eval must-haves, runtime vs adjacent, decision flow, trace hooks.
  - Patterns, agent components.

### Generate–Evaluate–Reflect (explicit QA loops)

- **What it is.**
  A structured loop where a generator produces candidates, an evaluator or judge scores them against a rubric, and an optional reflector guides retries.

- **What changes for SWEs vs single-call.**
  - You now deal with loops and budgets (max attempts, latency, token cost).
  - You need to log per-attempt verdicts and reasons, not just final "pass/fail," to debug where the loop is failing (generator vs evaluator vs rubric). Rubrics, judges, and regression strategy tie to General agent evaluation.

- **What to look up.**
  - GER cheatsheet — pattern topologies (linear, closed-loop, gated), optional grounding/rubric steps, eval must-haves, runtime vs adjacent, decision flow.
  - Patterns, agent components.
