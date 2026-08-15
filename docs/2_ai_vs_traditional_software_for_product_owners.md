# Working With AI and Agentic Systems

*Internal reference for non-technical subject matter experts (SMEs) and product owners who shape AI-powered products.*

> **Scope:** How to think about AI-backed behavior and "agents" at a product level — what they're good at, where they fail, and which design choices you can and should influence. Building and operating these systems is closer to **running experiments in a laboratory** than to **mass-producing identical widgets**.

**On this page:** Core ideas (table · lab headline) · Do you need an agent? (Part 2 patterns) · Common misconceptions · Operating principles · Designing single-step AI features · Designing agentic systems · Design canvas

---

## Core ideas

### AI as a "good but imperfect" assistant

- AI systems don't follow fixed rules like traditional software. They are more like **very capable assistants** that usually do the right thing, but not always on every request.
- Success is about **how often** they behave as intended across many real examples, not about being perfect on a few hand-picked cases.

### Agents as "multi-step workers," not just chatbots

- A simple AI feature answers a question or drafts content in **one step**.
- An **agentic system** chains multiple steps: it can look things up, call tools, update records, and come back with a result — more like a junior colleague following a checklist over time.
- That extra power introduces extra risk: bad **sequences of actions**, not just bad answers.

### At a glance: traditional software vs single-step AI vs agents

| Lens | Traditional software | Single-step AI | Agentic systems |
|---|---|---|---|
| What the user gets | Predictable behavior from fixed rules | One answer or draft per request | A sequence of steps (lookups, tools, updates) over time |
| How to judge quality | Right or wrong against a spec | **How often** it's good across real inputs—not a few demos | Safe, useful **journey**, not only a polished final message |
| Typical failure | Errors, crashes, obvious bugs | Sounds fine but is wrong, biased, or off-scope | Wrong action, wrong order, wrong stop—even if the ending looks good |
| How teams get better at it | Fix code; rerun tests | Run experiments: examples, prompts, evals, monitoring—hold conditions as stable as you can | Same, plus **experiments on journeys**: tools, permissions, where humans step in |

---

### We're in a laboratory, not a manufacturing plant

- **Manufacturing** (how much traditional software feels): you lock a design, ship it, and expect the **same** behavior for the **same** inputs until a clear code change explains a difference.
- **Laboratory** (how AI-backed products usually work): behavior depends on **models, data, prompts, tools, and real usage**. You learn what's true by **trying changes, under realistic conditions, with something you measure**—not by treating the first slick demo as proof.
- That experimental path means you **can't always predict** when something will be adequate for production use—only what you'll try next, under what conditions, and what evidence would justify broader rollout. In practice, many AI-backed products are still shipped in an *inadequate* state **on purpose**—within agreed scope, safeguards, and monitoring—to collect data that can be used to improve behavior.
- If that sounds slower than a release train, good: you're trading false certainty for **controlled learning**. Later sections are easier to use when this picture is shared across product, SMEs, and engineering.

**Day-to-day habits** (experimental design as a shared discipline—not statistics for its own sake):

- **What you are trying to learn or decide** — What behavior or outcome are you testing, and what would **convince** you (and stakeholders) that a change is safe and better?
- **Realistic conditions** — Examples and scenarios that reflect **messy production reality**, not only polished demos or a few favorite inputs.
- **What you will measure** — Signals you can revisit when something changes: rubrics, sampling, error or escalation rates, turnaround time, human spot-checks—whatever fits the risk.
- **Change one thing at a time (when you can)** — So when quality moves, you can attribute **why**, and for **which** users or journeys—instead of arguing from anecdotes alone. In real launches, teams often **bundle** changes (model, prompt, tools, routing, policy) on one timetable; that's normal, but it needs **extra care**: agree what you're trying to learn, what you'll watch, and whether you can **stage** or **compare** (e.g. holdouts, canaries) so bundled updates don't become impossible to interpret.

Engineering builds the harness and instruments; product and domain experts help **frame the questions, the test bed, and what "good enough" means**. Many misconceptions in Common SME misconceptions appear when teams slip into a **manufacturing posture**—ship the demo, move on—instead of **lab** discipline.

---

## Do you need an agent?

### Decision flow (yes / no)

Use this as a **triage**, not a rule of law—your Applied AI and engineering partners should still challenge the conclusion. **Answer in order.**

| # | Question | If No | If Yes |
|---|---|---|---|
| 1.1 | Can the outcome be delivered with **one model call** (one answer or draft per user request), maybe with lookup behind the scenes, without a multi-step "do A, then B, then C" story you care to supervise? | Continue to 1.2. | Stop: start with a **single-step AI** feature (Designing single-step AI features); revisit an agent only if you outgrow that shape. |
| 1.2 | Could the work be drawn as a **single flowchart** that rarely changes shape—same sequence of system steps with only obvious branches—such that a **fixed workflow** (traditional automation, orchestration, or hard-coded integration) is enough? | Continue to 1.3. | Stop: prefer **deterministic workflow** first; an LLM agent adds cost, variance, and governance you may not need. |
| 1.3 | Does the **next step need to depend on what the system just learned mid-run** (unexpected tool results, conflicting data, user corrections, retries with different tools)? | Stop: go back to 1.2 with engineering—you may still have a workflow problem dressed as an "agent." | Stop: strong candidate for an agentic design—use Designing agentic systems; invest in permissions, reversibility, and human touchpoints if steps have real **side effects** (writes, sends, money). |

### Part 2 — Which architecture conversation comes first?

Use this **only if Part 1 row 1.3 was Yes** (you're committed to an agent). **Answer in order** (2.1, then 2.2; then 2.3). These rows are **not mutually exclusive**—several can be Yes for one product. They tell you which pattern doc to prioritize first with engineering; Applied AI still composes them (for example, route first, then plan and act or draft and check inside a lane).

| # | Question | If No | If Yes |
|---|---|---|---|
| 2.1 | Do different requests need **different handlers** (separate tools, models, or clearly different agent paths)? | Continue to 2.2. | **Prioritize** Routing cheatsheet for "which path owns this?" Then revisit 2.2–2.3 for what happens inside each path. |
| 2.2 | Is the core loop **produce a candidate → check it** (rubric, policy, judge) **→ optionally revise** before finalizing or before risky tools run? | Continue to 2.3. | **Prioritize** Generate–evaluate–reflect cheatsheet. |
| 2.3 | Do you need **plan** (intent, ordered steps) clearly separated from **execution** (tool calls, writes)—so "what we meant" vs "what we did" is first-class for accountability, logging, or modeling? | Use Designing agentic systems (especially Step 4) with engineering; patterns may still layer in later. | **Prioritize** Planner–executor cheatsheet. |

---

## Common misconceptions

If you hear something like this, use the right-hand column as a quick correction. Details still matter—use this table as a scan, not a substitute for team discussion. Most rows are symptoms of **skipping experiments** (weak test conditions, no agreed measures, or treating one happy path as "done").

| If you hear... | Healthier mental model |
|---|---|
| "If the demo looks good, we're ready." | Demos use cherry-picked cases. You care about the **whole** population of real, messy requests. |
| "We'll fix it by improving the prompt." | Wording helps, but many gaps are **missing examples, rules, or guardrails**—not phrasing alone. |
| "A newer model automatically means a better product." | Upgrades help on average and can still **regress** behaviors you rely on. Treat every change as a release. |
| "Nothing crashed, so we're fine." | AI often fails **silently**: confident tone, wrong substance. Monitor quality, not only errors. |
| "The agent will do what our best SME would do." | It follows **your** patterns and permissions. Vague instructions → improvisation you may not want. |
| "Human review only at the end (if at all)." | **Where** humans step in (before, during, after) is a product decision that drives **risk, cost, and speed**. |

---

## Operating principles

Use these tables when you're writing requirements or reviewing a design. They pair with the deeper sections below. Think of each principle as part of **good experimental hygiene** — things you want defined *before* you argue about model upgrades or prompt tweaks.

### Single-step AI features

| Principle | What to do in practice |
|---|---|
| Define "good enough" in examples | Replace adjectives ("high quality") with **concrete good / bad** outputs the team can test against. |
| Think in percentages | Agree what "acceptable" means (e.g. right on ≥ X% of the cases you care about). |
| Match tests to real life | Include **edge cases**, rare-but-important scenarios, and tricky inputs—not only happy paths. |
| Plan for drift | Schedule **periodic quality reviews**; users, data, and models change over time. |

### Agentic systems (add these on top)

| Principle | What to do in practice |
|---|---|
| Think in journeys | Ask: "Were the **steps** right for a safe outcome?" A good ending via **unsafe** steps still fails. |
| Permissions before cleverness | Set **what it may touch** (systems, data, actions) before debating how "smart" it is. |
| Match autonomy to risk | Low impact + easy undo → more autonomy. **Messages, records, money** → tighter rules or approval. |
| Design human touchpoints | Decide: **plan review**, **per-step approval**, **pause and escalate** when stuck, or **sampling** in production—or a mix. |

---

## ✎ Designing single-step AI features

Use this when you are talking about features like "summarize this note," "draft a reply," or "answer this question" in one shot. Treat each feature as a *small experiment program*: you are defining conditions, outcomes, and how you'll know if a change actually helped.

### Questions to answer together with the AI/SWE teams

Walk the rows with your engineering and AI partners; each row is a conversation starter—and later, part of how you **reproduce** and **compare** behavior across changes (the lab notebook, in plain language).

| Topic | Questions to align on |
|---|---|
| Goal and users | What problem does this solve, and for whom? How will they **know it worked**? |
| What good looks like | A small set of **real examples**: good, almost good, unacceptable. What must it **never** do (tone, jargon, invented facts)? |
| Tolerance for mistakes | If it's wrong, what happens? Rate impact **low / medium / high** (annoyance, extra work, compliance or safety). |
| Review and feedback | Can users fix or flag outputs? Who owns feedback, and **how often** do you review it? |
| Guardrails | Topics, data, or user segments that are out of scope. Phrases or behaviors that are always unacceptable. |

---

## Designing agentic systems

Now extend that thinking to agents that can take *multiple* steps and use tools (APIs, databases, workflows). Agentic products are **multi-variable experiments**: changing the plan, a tool, or a permission can all move outcomes—so clarity on **what you're holding constant** and **what you're testing** matters even more than for single-step features.

The steps below are not exhaustive—they describe **common** situations so you and your team have a shared starting point. If your mission, risk profile, or tools don't line up with this flow, **work with the Applied AI team** to adapt the design rather than forcing your use case into a generic checklist.

### Step 1 — Clarify the mission

- What is the **end goal** from the user's perspective? (e.g., "keep this customer account up to date," "generate a first draft of a treatment plan for review.")
- When do we consider the mission "done"?

### Step 2 — Outline the high-level steps

Without worrying about models or prompts, list the steps a careful human would take, for example:

1. Gather relevant information.
2. Check current status in system X.
3. Draft suggested changes.
4. Get approval from role Y.
5. Apply changes in systems X and Z.
6. Send a summary to the user.

This becomes the **trajectory** you want the agent to follow.

### ✎ Step 3 — Classify risk and reversibility

For each step in your story, classify it using the row that fits best. High impact or hard-to-undo steps usually need **human review** or stricter rules.

| Kind of step | What it does | Ask yourself |
|---|---|---|
| Read-only | Looks up data; nothing persisted | Still wrong answers can mislead—how bad is a wrong read? |
| Draft-only | Proposes text or changes; nothing committed | Is the draft visible to customers or only internal reviewers? |
| Real effect | Writes, sends, deletes, or charges | Can you **undo**? If not, what's the blast radius (who is affected)? |

Then, for each step, note **impact if wrong** (low / medium / high) and **reversible?** (yes / no / only with effort).

### Step 4 — Decide where humans stay in the loop

Use this as a menu—you can combine patterns (e.g. plan review + pause and escalate).

| Pattern | What it means | Often fits when... |
|---|---|---|
| Plan review | Human approves or edits the **plan** before important steps run. | The sequence matters; mistakes are expensive. |
| Step approval | Human must approve specific high-risk actions (send, commit, bill). | Individual actions are irreversible or customer-visible. |
| Pause and escalate | Agent runs alone but stops and asks a human when unsure, blocked, or information conflicts. | Most work is routine; ambiguous cases need a person. |
| Sampling and audits | Humans review a **sample** of completed journeys. | High volume, lower per-item risk; you still need safety nets. |

If engineering names design patterns: **Planner–executor** is the usual label when plan and execution are separated (closely related to plan review and step structure above). **Routing** applies when different requests should go to different handlers (tools, flows, or models). **Generate–evaluate–reflect** applies when the system proposes output, scores it against a rubric or judge, and may revise before you see a final result.

### Step 5 — Define what must never happen

"Never events" matter more than small wording issues. Call them out so engineering can enforce **hard boundaries** and monitoring.

| Never event | Why product should name it explicitly |
|---|---|
| Acting outside allowed scope (wrong system, tenant, or segment) | Drives access rules and alarms—not something to "handle in the prompt" alone. |
| **Irreversible** actions without required approval | Defines which steps must be gated or blocked. |
| Ignoring **stop rules** or **escalation** triggers | Defines when the system must halt, not improvise. |

---

## A simple design canvas for SMEs

You can use this as a checklist when you bring a new idea to the AI/SWE teams—roughly, **one page that states your experiment**: what you're trying to achieve, under what constraints, and how you'll know if it's working.

**1. Use case**
- One sentence: What do you want the AI or agent to do?

**2. Users and value**
- Who benefits?
- How does this help them do their job better or faster?

**3. Type of system**
- ☐ Single-step AI feature (one request → one answer or draft)
- ☐ Agentic system (multiple steps, tools, and actions over time)

**4. What "good" looks like**
- 3–5 example scenarios with desired outputs or outcomes.
- 2–3 example scenarios of "this would be bad/unacceptable."

**5. Risk and reversibility**

For each important action or decision:
- Impact if wrong: low / medium / high.
- Reversible? yes / no / only with significant effort.

**6. Human involvement**

For this use case, we expect humans to:
- ☐ Approve the plan before the agent runs.
- ☐ Approve specific high-risk steps.
- ☐ Handle only edge or ambiguous cases (when the agent pauses and escalates).
- ☐ Periodically review samples of completed work.
- ☐ Other: _______________

**7. Hard boundaries**
- Systems/data the AI/agent may use: _______________
- Systems/data or user segments it must **never** touch: _______________
- Actions that must never be taken without human approval: _______________

**8. Success and monitoring**
- How will we know this is working over time? (e.g., turnaround time, error rate, number of escalations, user satisfaction.)
- How often should we review performance together? (e.g., weekly, monthly.)
