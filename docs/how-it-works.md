---
title: Morphism Engine: How It Works
description: Architecture-first technical narrative of Morphism Engine execution from DAG parse through synthesis, formal verification, execution, and cache reuse.
slug: /how-it-works
---

## End-to-End Pipeline Summary

Morphism Engine executes a typed command graph in five stages:

1. DAG Parse
2. Schema Inference
3. Transformation Synthesis
4. Formal Verification
5. Execution + Caching

Pipeline contract in one sentence: every edge in the DAG must satisfy `producer.output_schema == consumer.input_schema`, or Morphism must inject a verified bridge node (`AI_Bridge_Functor`) before execution proceeds.

Stage-by-stage data flow (diagram-friendly):

| Stage | Input | Internal IR / Contract | Decision Points | Output | Failure Surface |
|---|---|---|---|---|---|
| DAG Parse | CLI string with `|` and optional `|+ (...)` | `MorphismPipeline` with `FunctorNode` / `NativeCommandNode`; adjacency via `parents` + `children` | linear append vs branch fan-out; known tool vs native command | root nodes + ordered node list (`all_nodes`) | parse ambiguity, unknown command execution deferred to runtime |
| Schema Inference | Native command stdout text | `Schema` object (`JSON_Object`, `CSV_Data`, `Plaintext`) | JSON parse success, CSV sniffer heuristic, fallback | concrete `output_schema` for native node | ambiguous data classified as fallback `Plaintext` |
| Synthesis | source schema + target schema (+ config) | candidate lambda string (`code_str`) + compiled callable (`func`) | cache hit/miss, compile pass/fail, retry loop | bridge candidate | synthesis timeout, invalid lambda syntax, unsafe logic |
| Verification | `source_schema`, `target_schema`, candidate transform | Z3 constraints + runtime dry-run guard | UNSAT/SAT/unknown, numeric vs non-numeric constraints | `True` (safe) / `False` (unsafe) / exception | `VerificationFailedError`, rejected candidate |
| Execution + Caching | DAG + optional bridge insertions | async traversal with node `output_state` snapshots | deferred mismatch resolution at runtime; cache store/evict | final leaf result + persisted mapping in SQLite | `EngineExecutionError`, runtime schema mismatch without LLM |

## Stage-by-Stage Deep Dive

### 1) DAG Parse

Implementation model:

- Parse entrypoints are in shell and TUI command handlers.
- `|` builds a linear chain via repeated `append(...)`.
- `|+ (a,b,...)` builds branch children via `add_branch(parent, children)`.
- Known tool names map to typed `FunctorNode` instances.
- Unknown commands are wrapped as `NativeCommandNode` with `Pending` schemas and deferred resolution.

Data contract:

- Node contract: `{name, input_schema, output_schema, executable, parents[], children[], output_state}`.
- Graph contract: `root_nodes[]` + insertion-ordered `all_nodes[]` for backward-compatible history/inspection.

Boundary discovery:

- Compile-time boundary check in `append` / `add_branch` when schemas are concrete.
- Runtime boundary check in execution when `Pending` is resolved to concrete schema.

Stream semantics and ordering assumptions:

- Each node consumes one in-memory value and emits one in-memory value.
- Native command stdin/stdout is materialized as whole strings (not token streams).
- Branch fan-out runs child edges concurrently (`asyncio.gather`).
- Return value is last leaf by insertion order for compatibility; all branch outputs remain in node states.

Fallback behavior:

- Unknown command is not rejected at parse-time; it is attempted as subprocess execution later.

Failure modes and surfacing:

- Structural/type mismatch with no LLM: `SchemaMismatchError` surfaced in shell/TUI as pipeline error.
- Native command process failure: wrapped as `EngineExecutionError` with exit code and stderr.

Latency/cost profile:

- Parse cost is string splitting + regex matching + node allocation: low.
- Optimization levers: keep command syntax simple, avoid unnecessary branch expansion.

### 2) Schema Inference

Implementation behavior:

- Inference runs after native subprocess completes and stdout is captured.
- Heuristic order:
  1. Parse as JSON object/array -> `JSON_Object`
  2. Detect CSV dialect over multi-line content -> `CSV_Data`
  3. Otherwise -> `Plaintext`

Static vs sampled inference:

- Current implementation is sampled/dynamic at runtime from observed stdout payload.
- There is no static, ahead-of-time schema derivation from command signatures.

Confidence and ambiguity handling:

- Confidence is implicit via ordered heuristics, not numeric.
- Ambiguous payloads resolve conservatively to `Plaintext`.
- Empty output maps to `Plaintext`.

Data contract:

- `infer_schema(str) -> Schema`; native node mutates `output_schema` from `Pending` to inferred concrete schema.

Failure modes and surfacing:

- Invalid JSON simply falls through to next heuristic (no user-visible hard error).
- Subprocess-level failures occur before inference and are surfaced as `EngineExecutionError`.

Latency/cost profile:

- O(size of output) parse/sniff work; dominates only for large stdout payloads.
- Optimization levers: reduce output volume or shape output explicitly (JSON preferred for stability).

### 3) Transformation Synthesis

Prompt-to-transform architecture:

- Triggered on schema mismatch when an LLM client is configured.
- Pipeline first checks local cache for existing transform by `(source_schema_name, target_schema_name)`.
- On miss, synthesizer produces lambda code string.
- Candidate is compiled with `eval` under restricted helper globals (`json`, `math`, `re`).

Constraint injection and policy:

- Prompt includes source/target schema names, types, and constraint strings.
- Prompt injects domain-specific typing instructions (for JSON-derived string inputs, parse via `json.loads`).
- Additional semantic guardrail exists for `Int_0_to_100 -> Float_Normalized`: anchor checks at `{0,50,100}`.

Deterministic controls and reproducibility knobs:

- `MORPHISM_MODEL_NAME`
- `MORPHISM_OLLAMA_URL`
- `MORPHISM_MAX_SYNTHESIS_ATTEMPTS`
- `MORPHISM_LLM_REQUEST_TIMEOUT`
- Deterministic test path: `MockLLMSynthesizer`.

Fallback behavior:

- Cached transform compile failure -> ignore cache entry and synthesize fresh candidate.
- Verification failure -> retry until attempt budget exhausted.

Failure modes and surfacing:

- Network/timeouts/invalid response -> `SynthesisTimeoutError`.
- Exhausted attempts after repeated unsafe candidates -> `VerificationFailedError` with last error.

Latency/cost profile:

- Dominated by LLM round-trip and retries.
- Optimization levers: increase cache hit ratio, reduce attempt budget for CI determinism, use local model.

### 4) Formal Verification

What is proven:

- Candidate transform preserves target schema constraints for all inputs satisfying source constraints, when constraints are numeric and representable.
- For non-numeric constraint domains, Morphism falls back to runtime postcondition checks plus dry-run type guard.

How SMT constraints are derived:

- Parse source and target constraints from strings of the form `lo <= x <= hi`.
- Build source-domain constraint over symbolic variable `x`.
- Translate lambda AST to Z3 expression `y = f(x)` for supported operators/functions.
- Assert negation of target postcondition and query solver.

SAT/UNSAT interpretation in user-facing terms:

- `UNSAT`: no counterexample exists -> proof pass -> transform accepted.
- `SAT`: counterexample exists -> proof fail -> transform rejected.
- `unknown`: solver timeout/indeterminate -> `VerificationFailedError`.

Additional safety checks:

- Dry-run executes candidate on schema-appropriate dummy data to reject type-shape errors early.

Failure modes and surfacing:

- Unsupported lambda AST patterns -> verifier error -> candidate rejected.
- Repeated rejection until attempt cap -> surfaced as final `VerificationFailedError`.

Latency/cost profile:

- Usually low versus synthesis, bounded by `MORPHISM_Z3_TIMEOUT_MS`.
- Optimization levers: simplify constraints/transforms, tighten timeout for CI.

### 5) Execution + Caching

When transforms are applied:

- Compile-time insertion during `append`/`add_branch` if mismatch is known.
- Runtime insertion inside traversal when deferred `Pending` schemas resolve into mismatch.

Side-effect boundaries:

- Native command nodes can produce external side effects by definition (process execution).
- Synthesized bridge nodes are pure Python callables in-process.

Idempotency considerations:

- Graph execution is not globally idempotent if native commands are side-effectful.
- Cache writes are idempotent by key (`INSERT OR REPLACE`).

Caching mechanics:

- Storage: SQLite file `.morphism_cache.db` in current working directory.
- Key: SHA-256 of `"{source_name}::{target_name}"`.
- Value: lambda string plus source/target names + timestamp.

Invalidation behavior:

- On cache hit, candidate is recompiled and reverified before acceptance.
- If cached candidate fails verify, entry is deleted and synthesis resumes.
- Manual invalidation: remove `.morphism_cache.db`.

Portability/sharing in team environments:

- Cache is local by default; team sharing requires explicit distribution of SQLite artifact or promotion to central cache service (not built-in).
- Portability risk: cache entries are schema-name keyed; teams should version-lock Morphism and clear cache on incompatible upgrades.

Failure modes and surfacing:

- Node callable raises -> wrapped as `EngineExecutionError` with node context.
- Runtime mismatch with no LLM client -> `SchemaMismatchError`.

Latency/cost profile:

- Cache hit path: compile + verify only, much cheaper than synthesis path.
- Branch execution can improve throughput via parallel child tasks but preserves last-leaf return compatibility behavior.

## Full Trace Example

Trace: `emit_raw | render_float`

Initial graph:

- Node A (`emit_raw`): `Int_0_to_100 -> Int_0_to_100`
- Node B (`render_float`): `Float_Normalized -> String_NonEmpty`
- Boundary mismatch detected at `A.out != B.in`

Resolution path:

1. Cache lookup for key `Int_0_to_100::Float_Normalized`.
2. If miss, synthesize candidate code (example: `lambda x: x / 100.0`).
3. Compile candidate into callable.
4. Verify candidate:
   - Source domain: `0 <= x <= 100`
   - Target domain: `0.0 <= f(x) <= 1.0`
   - Solver checks `exists x: source(x) and not target(f(x))`
   - Returns `UNSAT` -> pass.
5. Insert bridge node:
   - `AI_Bridge_Functor`: `Int_0_to_100 -> Float_Normalized`
6. Execute DAG:
   - A returns `50`
   - Bridge returns `0.5`
   - B returns `[RENDERED UI]: 0.5`
7. Persist mapping in cache.

Resulting graph:

- `emit_raw -> AI_Bridge_Functor -> render_float`

## Guarantees, Limits, and Failure Semantics

Operational guarantees:

- Every accepted bridge candidate passes the active verification gate before insertion.
- Cached bridges are revalidated before reuse; stale/unsafe entries are evicted.
- Execution errors are wrapped with node/process context for user-facing diagnostics.

Best-effort behavior:

- Native schema inference is heuristic and payload-dependent.
- LLM synthesis quality depends on model behavior and prompt adherence.
- Non-numeric constraint spaces rely on runtime postcondition checks rather than full symbolic proof.

Hard limits and assumptions:

- Constraint parser expects bounded-range forms like `lo <= x <= hi` for symbolic reasoning.
- Lambda AST translator supports a constrained subset of Python expressions.
- Pipeline return value is the last leaf for backward compatibility, not a full branch result map.

Failure semantics:

- Parse/link mismatch without LLM -> immediate `SchemaMismatchError`.
- Candidate synthesis/verification exhaustion -> `VerificationFailedError`.
- Runtime callable/process failure -> `EngineExecutionError`.

## Performance Characteristics

Approximate stage cost profile (relative):

- DAG parse/link: low
- Inference on stdout: low to medium (data-size dependent)
- Cache lookup/store: very low
- Verification: low to medium (constraint complexity + timeout)
- Synthesis: high and dominant on misses

Optimization levers by stage:

- Parse/link: reduce command churn; pre-register common tools.
- Inference: emit stable JSON from native commands to avoid ambiguity.
- Synthesis: maximize cache hit ratio; use deterministic model settings; lower attempt budget in CI.
- Verification: tune `MORPHISM_Z3_TIMEOUT_MS` for environment class.
- Execution: branch where independent workloads benefit from concurrency.

## Design Trade-offs

1. Heuristic runtime inference vs declared static schemas for all commands
- Chosen: heuristic runtime inference for native commands.
- Why: enables immediate interoperability with arbitrary shell commands.
- Cost: ambiguity and payload sensitivity.

2. LLM-generated code + formal gate vs rule-only adapters
- Chosen: synthesis then proof.
- Why: broader transform search space while preserving safety gate.
- Cost: synthesis latency and model nondeterminism.

3. SQLite local cache vs distributed cache service
- Chosen: local SQLite WAL cache.
- Why: zero external dependency, low latency, robust local persistence.
- Cost: no built-in team-wide sharing or multi-host coherence.

4. Last-leaf return compatibility vs explicit multi-output API
- Chosen: last-leaf compatibility return, node-state introspection for full graph outputs.
- Why: minimal breakage for existing shell UX.
- Cost: branch results are implicit unless inspected.

5. Restricted lambda AST support vs full Python semantics in verifier
- Chosen: constrained subset.
- Why: tractable symbolic translation and predictable proof behavior.
- Cost: some valid Python transforms are unverifiable symbolically.

## Related Docs links (Architecture, Verification, Transformations & Synthesis)

- Architecture: [Pipeline Core](../src/morphism/core/pipeline.py), [Node Model](../src/morphism/core/node.py), [CLI Parse Paths](../src/morphism/cli/shell.py)
- Verification: [Z3 Verifier](../src/morphism/math/z3_verifier.py), [Schema Definitions](../src/morphism/core/schemas.py)
- Transformations and Synthesis: [LLM Synthesizer](../src/morphism/ai/synthesizer.py), [Cache Layer](../src/morphism/core/cache.py), [Runtime Inference](../src/morphism/core/inference.py)
