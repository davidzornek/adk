# Composability guide: routing, GER, and planner–executor

**Audience:** Principal engineers, staff sponsors, and tech leads aligning on **whether and how** to invest in an internal **Agent Development Kit (ADK)** (LangChain / LangGraph)—and the teams who will own it once funded. Sketch packages in this repo are **illustrative** of the target shapes, not a shipped product ADK.

This page supports **buy-in and shared vocabulary**: three **pattern families** (routing, GER, planner–executor), three **mechanisms** for expressing the same graphs (subclass, constructor injection, declarative YAML), how they **coexist**, and **one** composed reference topology (GER-as-planner inside planner–executor). It is written to **steer an ADK program**, not to implement one line-by-line here.

**Mechanisms are not mutually exclusive.** Subclassing, constructor injection, and declarative YAML are **coexisting options** you can offer in the same package—different call sites or teams pick the surface that fits, and evolving the ADK is often **additive** (add a YAML factory or injectable shell alongside existing bases) rather than an either-or rewrite. **Choosing a mechanism** (end of page) lays out pros, cons, and **when to use** each in one table; in product strategy, treat them as a **menu** and a plausible **development path**, not competing religions.

Sketch packages in this repo (not production; same spirit as pattern demos):

| Pattern | Package | Representative types |
|---|---|---|
| Routing | `6_routing/routing_base_classes/` | `ConditionalEdgesRouterAgent`, `RoutingState`, `BaseRoutingAgent` |
| Generate–evaluate–reflect | `7_generate_evaluate_reflect/generate_evaluate_reflect_base_classes/` | `BaseGenEvalReflectAgent`, `GenEvalReflectState` |
| Planner–executor | `8_planner_executor/planner_executor_base_classes/` | `PlanThenExecuteAgent`, `InterleavedPlanActAgent`, `PlannerExecutorState` |

Reality check: Wiring all three into one composable stack is an **engineering aspiration** in the sketch bases; the **graphs described below** are the shapes you target in product code. Treat gaps as normal integration work.

**Further reading:** Routing cheatsheet · GER cheatsheet · Planner–executor cheatsheet · Future development — pattern factory roadmap

---

## Pattern families (orthogonal, composable)

- **Routing** — Chooses which capability or subgraph owns the turn (conditional edges, classifiers, policy routers).
- **Generate–evaluate–reflect (GER)** — Shapes *quality loops*: draft (or plan candidate) → evaluate → reflect → retry.
- **Planner–executor** — Decomposes work into *plans* and *executes* steps (often tools), with optional replanning.

**Typical stacks** (compose these as nodes, runnables, or subgraphs). This guide walks **one** composed shape in detail—**GER as planner** (item 5); the rest are context for adjacent designs.

1. Route → GER — Route into a subgraph that runs generate / evaluate / reflect on user-facing copy.
2. Route → planner–executor — Route into a subgraph that plans and executes tools.
3. Planner–executor → GER — Each plan step or final artifact passes through a GER loop before sink.
4. GER inside execution — A tool or sub-call drafts and gates before committing side effects.
5. **GER as planner** — GER produces or repairs a **plan artifact** until a rubric passes; **execute** runs only after that (see Composed topology below).

---

## Three mechanisms (definitions)

These are **different ways to author** the same kinds of LangGraph / `Runnable` topologies—not different pattern families. An internal ADK may start with one mechanism and layer others; see above—mechanisms can coexist as options in the same package.

### Subclass

Subclass means: extend a sketch **base class** from this repo (or your ADK's equivalent) and **override** template methods (`decide_route`, `generate`, `produce_plan`, `execute_plan`, ...). Behavior lives in Python methods on a named class; the graph builder or `compile()` path wires those methods into nodes. The type system and IDE jump-to-definition show **which hooks** you own.

```python
from dataclasses import replace

class AcmeRouter(BaseRoutingAgent):
    def decide_route(self, state: RoutingState) -> RoutingState:
        label = "billing" if "invoice" in state.user_message else "default"
        return replace(state, route_label=label)

    def invoke_handler(self, state: RoutingState) -> RoutingState:
        return replace(state, handler_output=f"ok:{state.route_label}")
```

**Illustrative compiled graph** (hooks above map to graph nodes after `compile()`):

```
start → decide_route → invoke_handler → end
```

### Constructor injection (and factory args)

Injection means: at construction time (or via a small factory), pass in **already-built** collaborators—typically LangChain `Runnable`s, callables, or compiled subgraphs—that implement part of the loop (planner, executor, router policy, GER rubric runner, ...). The outer shell (loop or graph) stays generic; **behavior varies by what you pass in**, not by subclass name. The ADK should document the **expected state shape** and whether nested `invoke` receives `RunnableConfig` for tracing.

```python
from langchain_core.runnables import Runnable

class AcmePlanner(BasePlannerAgent): ...  # sketch base + Runnable
class AcmeExecutor(BaseExecutorAgent): ...

planner: Runnable = AcmePlanner(llm=my_llm)
executor: Runnable = AcmeExecutor(tools=my_tools)

agent = PlannerExecutorShell(planner=planner, executor=executor)
```

**Illustrative compiled graph** — Injected planner / executor `Runnable`s typically sit behind `plan` and `execute` nodes with conditional edges after each (not a single straight line). One representative product shape: `plan → draft`, `plan → execute`, or `plan → stop`, and `execute → plan` (loop) or `execute → draft` (e.g. iteration cap)—so `draft` is reachable from either leg.

```
start → plan → tool loop → draft / execute / stop → end
                              ↑_____________________|
```

### Declarative YAML

YAML (or JSON, TOML, etc.) means: describe **pattern, config, nested subgraphs, and edges** in a file. A **factory** loads the file, validates it, and emits a new Python `type`—a subclass of a registered sketch base—whose hooks close over the spec. Product code then **instantiates** that class (runtime deps, models, tools) and `compile()`s to the same `CompiledGraph` you could have built by hand—see `6_future_development.md`. Authors **change config**, not the inheritance line, subject to schema and review.

The **complete reference factory** below is self-contained (stub bases + tiny state dataclasses). If you try to execute it locally, add `pyyaml` (`pip install pyyaml`). In a real ADK, swap `GerSketchBase` / `PlannerExecutorSketchBase` for your shipped types (e.g. `BaseGenEvalReflectAgent`, `PlanThenExecuteAgent` from the foundations sketches) and replace the stub `invoke` chains with `Runnable` / LangGraph `compile()` while keeping the same `parse → recurse on subgraphs → type(name, bases, namespace)` structure.

**Example spec** (same shape as the roadmap example; not a file in this repo):

```yaml
# experiments/refund_analysis.yaml
pattern: planner_executor
name: RefundAnalysisAgent
version: "1.0"
config:
  planner_model: claude-3-5-sonnet
  max_replans: 3
  tools:
    - name: sql_query
      description: "Query refund tables"
subgraphs:
  quality_check:
    pattern: generate_evaluate_reflect
    config:
      rubric: "Plan must cover refund trends by cohort"
      max_iterations: 2
edges:
  planner: quality_check
  quality_check: executor
  executor:
    condition: should_replan
    mapping:
      replan: planner
      complete: END
```

**Illustrative compiled graph** (topology from the `edges:` block; `quality_check` is a nested GER subgraph in the spec):

```
start → planner → quality_check ⇄ replan → executor → complete → end
```

> **Note:** The following listing was drafted as an end-to-end illustration of the factory pattern. It has **not been exercised or reviewed** for reliable copy-paste runnability in your environment—treat it as documentation-shaped reference code.

**Complete reference factory** — end-to-end: load YAML → nested `AgentSpec` → `emit_for` recursion → `type(...)` per node. Stub bases stand in for your ADK sketch types; hook bodies close over `spec.config`. Conditional edges in YAML (e.g. `executor: condition: mapping:`) are not expanded into a second graph here—this sample wires the nested GER referenced from `edges.planner` into `produce_plan`; a production factory would emit LangGraph `StateGraph` from the same spec.

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

# --- stub sketch bases (replace with your ADK / foundations sketch imports) ---

@dataclass
class GerState:
    task: str
    candidate: str | None = None
    eval_pass: bool = False
    eval_rationale: str | None = None


class GerSketchBase(ABC):
    @abstractmethod
    def generate(self, state: GerState) -> GerState: ...

    @abstractmethod
    def evaluate(self, state: GerState) -> GerState: ...

    def reflect(self, state: GerState) -> GerState:
        return state

    def invoke(self, task: str) -> GerState:
        state = GerState(task=task)
        state = self.generate(state)
        state = self.evaluate(state)
        return self.reflect(state)


@dataclass
class PEState:
    task: str
    plan_artifact: tuple[str, ...] | None = None
    executed_steps: tuple[str, ...] = ()
    last_observation: str | None = None


class PlannerExecutorSketchBase(ABC):
    @abstractmethod
    def produce_plan(self, state: PEState) -> PEState: ...

    def validate_plan(self, state: PEState) -> PEState:
        return state

    @abstractmethod
    def execute_plan(self, state: PEState) -> PEState: ...

    def invoke(self, task: str) -> PEState:
        state = PEState(task=task)
        state = self.produce_plan(state)
        state = self.validate_plan(state)
        return self.execute_plan(state)


# --- parsed spec (one block per YAML mapping, including nested subgraphs) ---

@dataclass(frozen=True)
class AgentSpec:
    pattern: str
    name: str | None
    config: dict[str, Any]
    subgraphs: dict[str, AgentSpec]
    edges: dict[str, Any]
    version: str | None = None


def load_and_validate(path: Path) -> AgentSpec:
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("root YAML must be a mapping")
    if "pattern" not in raw:
        raise ValueError("missing required key: pattern")
    return _dict_to_spec(raw)


def _dict_to_spec(d: dict[str, Any]) -> AgentSpec:
    subgraphs: dict[str, AgentSpec] = {}
    for key, node in (d.get("subgraphs") or {}).items():
        if not isinstance(node, dict):
            raise ValueError(f"subgraphs.{key} must be a mapping")
        subgraphs[key] = _dict_to_spec(node)
    return AgentSpec(
        pattern=d["pattern"],
        name=d.get("name"),
        config=dict(d.get("config") or {}),
        subgraphs=subgraphs,
        edges=dict(d.get("edges") or {}),
        version=d.get("version"),
    )


def _python_class_name(spec: AgentSpec, subgraph_key: str | None) -> str:
    if spec.name:
        return str(spec.name)
    key = subgraph_key or "generated"
    stem = "".join(part.capitalize() for part in key.split("_"))
    return f"{stem}Ger" if spec.pattern == "generate_evaluate_reflect" else f"{stem}Planner"


def _make_ger_class(spec: AgentSpec, cls_name: str) -> type:
    cfg = spec.config

    def generate(self, state: GerState) -> GerState:
        rubric = str(cfg.get("rubric", ""))
        return replace(state, candidate=f"[plan-candidate]{state.task}|{rubric[:48]}")

    def evaluate(self, state: GerState) -> GerState:
        return replace(
            state,
            eval_pass=True,
            eval_rationale=str(cfg.get("rubric", "ok")),
        )

    return type(
        cls_name,
        (GerSketchBase,),
        {"generate": generate, "evaluate": evaluate},
    )


def _make_pe_class(spec: AgentSpec, cls_name: str) -> type:
    nested_types: dict[str, type] = {
        key: emit_for(sub, subgraph_key=key) for key, sub in spec.subgraphs.items()
    }
    cfg = spec.config
    edges = spec.edges

    def __init__(self) -> None:
        self._nested: dict[str, Any] = {k: cls() for k, cls in nested_types.items()}

    def produce_plan(self, state: PEState) -> PEState:
        first_edge = edges.get("planner")
        worker = self._nested.get(first_edge) if first_edge else None
        if worker is not None:
            ger_out = worker.invoke(state.task)
            plan = (ger_out.candidate or "(empty)",)
            return replace(state, plan_artifact=plan)
        model = cfg.get("planner_model", "default")
        return replace(state, plan_artifact=(f"stub-plan:{model}",))

    def execute_plan(self, state: PEState) -> PEState:
        tools = cfg.get("tools") or []
        names = ",".join(str(t.get("name", "?")) for t in tools) if tools else "noop"
        steps = state.plan_artifact or ()
        obs = f"executed tools=[{names}] steps=" + "|".join(steps)
        return replace(state, executed_steps=tuple(steps), last_observation=obs)

    return type(
        cls_name,
        (PlannerExecutorSketchBase,),
        {
            "__init__": __init__,
            "produce_plan": produce_plan,
            "execute_plan": execute_plan,
        },
    )


PATTERN_REGISTRY: dict[str, Any] = {
    "planner_executor": _make_pe_class,
    "generate_evaluate_reflect": _make_ger_class,
}


def emit_for(spec: AgentSpec, *, subgraph_key: str | None = None) -> type:
    if spec.pattern not in PATTERN_REGISTRY:
        raise ValueError(f"unsupported pattern: {spec.pattern!r}")
    cls_name = _python_class_name(spec, subgraph_key)
    maker = PATTERN_REGISTRY[spec.pattern]
    return maker(spec, cls_name)


def build_subclass_from_yaml(path: Path) -> type:
    return emit_for(load_and_validate(path), subgraph_key=None)
```

**Call site** — `build_subclass_from_yaml` returns a **class** (subclass of the stub PE base above). The stub uses `invoke(task: str)`; a LangGraph ADK would instead expose `.compile()` on the generated type or a wrapper.

```python
from pathlib import Path

RefundAnalysisAgent = build_subclass_from_yaml(Path("experiments/refund_analysis.yaml"))
assert issubclass(RefundAnalysisAgent, PlannerExecutorSketchBase)

pe_state = RefundAnalysisAgent().invoke("summarize refund spikes by cohort")
# pe_state.plan_artifact, pe_state.last_observation, ...
```

---

## Design notes for ADK maintainers

*For teams **owning** the kit (subclass bases, injectable shells, optional YAML factory)—not every application author needs this on first read.*

- **Subclass.** Hooks stay visible to IDEs and code review; in LangGraph, mapping each hook to a **named node** usually aligns traces and operator playbooks with the diagram (LangSmith, on-call). When every small behavior tweak implies a new type, shift that slice to injection or YAML-generated classes instead of piling on subclasses.

- **Injection.** Pin the state shape (e.g. dataclass or TypedDict) and document invariants; forward `RunnableConfig` through nested `invoke` when tags, callbacks, or cancellation matter. Different teams can supply `Runnable`s into the same shell without forking bases. **Conditional edges** after both planner and executor legs are normal—see the Constructor injection diagram above.

- **YAML.** The generated subclass should `compile()` to the **same graph semantics** as hand-written Python—no parallel runtime. Pair a strict schema with **parity tests** (YAML → generated type → instance → compile vs a reference graph) on critical paths; roadmap and factory sketch in `6_future_development.md`.

---

## Composed topology: GER-as-planner inside planner–executor

**What this section is:** The **only** full composed topology spelled out end-to-end here—**planner–executor** where the **planner** is implemented as a **GER loop** (generate / evaluate / reflect on a plan candidate until a rubric passes), then **commit** materializes `plan_artifact`, and **execute** runs tools or steps. **Routing** (fan-out to sibling subgraphs) is *out of scope* for this walkthrough; see the Pattern families list above for other stacks.

**Mechanisms:** The **Mermaid** is the **shared target**—each approach below should materialize the **same node set and edges**. **Subclass** and **inject** are what most teams ship first; **YAML** is optional spec for variants, review, and non-Python authors, resolved through the same factory ideas as in **Declarative YAML** above.

**Contrast:** A minimal PE graph might use one `produce_plan` node; here that planning step is **expanded into GER**. **Injected** PE shells that add `draft / stop / loops` after `plan` and `execute` are still compatible—see the Constructor injection diagram earlier.

**Narrative:** Planning GER refines the plan until evaluation passes → `commit_plan` → `execute_plan` → end.

```
start → plan_ger_generate → plan_ger_evaluate → retry → plan_ger_reflect → (back to generate)
                                              ↓ pass
                                          commit_plan → execute_plan → end
```

*Diagram note: The figure expands planning into generate / evaluate / reflect so the GER pattern is visible. With subclass authorship, the outer planner–executor graph often has one planner node whose implementation `invoke`s a GER sketch instance; G/E/R then show up only **inside** that instance's own runnable or subgraph (LangSmith still traces them under that step).*

### Subclass

You implement **one** product type: a **subclass** of the planner–executor sketch (e.g. `PlanThenExecuteAgent` in `8_planner_executor/planner_executor_base_classes/`). Hold a `BaseGenEvalReflectAgent` (or your ADK's GER sketch) instance—typically constructed in `__init__` as `self._planning_ger = PlanQualityGER(...)`—that encapsulates the full generate / evaluate / reflect loop on a **plan candidate**. `produce_plan` is a **single** planning step at the PE layer: map state into the GER input shape, `self._planning_ger.invoke(...)` (or `ainvoke`), then map the accepted result back into `plan_artifact` on `PlannerExecutorState`. `execute_plan` is unchanged in role. The **outer** compiled graph registers one node for planning (the body of `produce_plan`), not three sibling `plan_g / plan_e / plan_r` nodes; injection differs because the kit usually wires the planning GER as its own subgraph with visible inner nodes.

```python
class RubricGatedPlanAgent(PlanThenExecuteAgent):
    """One planner step: delegate the whole GER loop to a GER sketch instance."""

    def __init__(self, ...):
        super().__init__(...)
        self._planning_ger = PlanQualityGER(...)  # BaseGenEvalReflectAgent subclass

    def produce_plan(self, state: PlannerExecutorState) -> PlannerExecutorState:
        ger_in = self._state_to_planning_ger_input(state)
        ger_out = self._planning_ger.invoke(ger_in)
        return self._merge_accepted_plan(state, ger_out)

    def execute_plan(self, state: PlannerExecutorState) -> PlannerExecutorState: ...
```

### Constructor injection

The **graph skeleton** (node names, conditional edges, commit boundary) lives in **one** generic builder inside the kit. Callers pass a **compiled planning GER subgraph** (often expanded to generate / evaluate / reflect nodes at the top-level graph) plus an **executor** `Runnable`. That contrasts with **subclass**: there the PE type owns a GER instance and the outer graph sees one planner node whose body runs that instance's loop. The ADK does **not** fork the skeleton per product—only **injected collaborators** change. Document the **state contract** once: what the planning subgraph must leave for `commit` and what `execute` may read; forward `RunnableConfig` through nested `invoke` when tracing matters.

```python
gated_pe = compose_ger_then_execute(
    plan_ger_subgraph=planning_ger_compiled,
    executor=executor_runnable,
)
```

### Declarative YAML

The spec names the outer pattern (`planner_executor`) and nests a `subgraphs` entry for the GER pattern that is the planning phase (`generate_evaluate_reflect`), with `config` for rubric, caps, models, etc. A factory walks the tree: **validate** each block, **emit** nested generated types or namespaces, **attach edges** so that "planning GER passed" routes to **execute** (sketch above: `on_pass: execute_steps`). The **diff** reviewers see is YAML, not Python structure—good for **experiment matrices** and SME-tuned knobs—at the cost of **factory + schema** ownership and **parity tests** against a reference subclass graph so config drift does not change semantics. **Same compiled artifact** as the other two mechanisms when the factory is correct.

```yaml
pattern: planner_executor
name: GatedPlanThenExecuteAgent
subgraphs:
  plan_quality:
    pattern: generate_evaluate_reflect
    name: PlanQualityGer
    config:
      rubric: multi_step_plan_schema
edges:
  start: plan_quality
  plan_quality:
    on_pass: execute_steps
```

---

## Choosing a mechanism

Pros, cons, and when to use — one table.

| Mechanism | Pros | Cons | Best when |
|---|---|---|---|
| **Subclass** | Explicit template methods; IDE navigation and refactors; type-checked overrides; natural for product-specific glue (e.g. overrides that wire nested collaborators or policy in one place). | Subclass sprawl; swapping behavior often means new types; onboarding must learn which base to extend. | One-off orchestration, thin glue over stable internal bases, or when **Python is the source of truth**. |
| **Inject** (constructor / factory args) | Reuse `Runnable`s and **compiled subgraphs** for the slots your kit defines (routers, planners, executors, quality loops, ...); fewer product types; easy fakes in tests; aligns with LCEL composition; nested subgraphs can be **expanded** to visible inner nodes when you want traces to match the diagram. | Two customization paths (inject vs override) unless the ADK documents a **default**; strict **state** contract; risk of dropping `RunnableConfig` / callbacks if not threaded. | Shared library components across services, multiple teams supplying runnables into the same shell, or when the same subgraph is dropped into several graphs. |
| **YAML** (not implemented in-tree) | Versioned experiments; diffs and review; non-SWE can tune variants; clear audit trail of **what config ran**; nested subgraphs match composed stacks declaratively. | Requires a **factory**, schema validation, and ops discipline; debugging indirection; drift between YAML and code if not guarded. | Experiment matrices, SME-tunable knobs, governed rollout of variants—see `6_future_development.md`. |

*Runnable graphs: For the clearest traces and on-call diagrams, prefer **explicit LangGraph nodes** for each meaningful step (including nested subgraph steps when your kit expands them) across routing, quality loops, planner–executor, and other composed shapes—even when behavior is injected. For **kit design tradeoffs** (state contracts, `RunnableConfig` parity tests), see Design notes for ADK maintainers above.*
