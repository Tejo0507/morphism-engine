---
title: Morphism Engine Pipelines
description: Operational guide to designing, validating, and scaling robust typed DAG pipelines with Morphism Engine.
slug: /pipelines
---

## Pipeline Execution Model

Morphism executes pipelines as a typed DAG of `FunctorNode` vertices.

Core model:

- Linear edges are created from `a | b | c`.
- Fan-out edges are created from `a |+ (b, c, d)`.
- Each edge must satisfy schema compatibility (`upstream.output_schema == downstream.input_schema`) or Morphism injects `AI_Bridge_Functor` after synthesis+verification.
- Unknown commands are wrapped as `NativeCommandNode` with `Pending` schemas and resolved after runtime output inference.

Stage boundaries and transformation insertion points:

1. Parse-time boundary check during `append`/`add_branch` for known schemas.
2. Runtime boundary check in execution when `Pending` resolves to inferred concrete schema.
3. In either path, mismatch triggers bridge resolution through cache -> synthesis -> verification.

Stream semantics and ordering guarantees:

- Node IO is value-based (whole payload per stage), not record-by-record streaming.
- Native subprocess stdout is fully materialized as text before inference.
- Child branches execute concurrently via `asyncio.gather`.
- Returned value is the last leaf by insertion order; full per-branch outputs are stored in node state.

Operational implication: treat Morphism as typed orchestration over stage payloads, not as a byte-stream passthrough engine.

## Core Pipeline Patterns

### Pattern A: Linear safe chain

Use when stage contracts are already aligned.

```text
emit_raw | render_float
```

Behavior:

- Detects `Int_0_to_100 -> Float_Normalized` mismatch.
- Inserts verified bridge (`x / 100.0`) and executes.

### Pattern B: Linear with native boundary

Use when shell/native command output type is unknown before runtime.

```text
echo '{"score": 85}' | render_float
```

Behavior:

- First stage inferred as `JSON_Object` at runtime.
- Boundary to `render_float` repaired via synthesized bridge (must parse JSON string).

### Pattern C: Fan-out branch

Use when one producer feeds independent consumers.

```text
emit_raw |+ (render_float, render_float)
```

Behavior:

- Parent output is propagated to each child branch concurrently.
- Mismatch checks are applied independently per edge.

### Pattern D: Guard stage before fragile consumer

Use a guard native command that exits non-zero on invalid payload.

```text
echo '{"score":85}' | python -c "import sys,json; d=json.load(sys.stdin); assert 'score' in d; print(d['score'])" | render_float
```

Behavior:

- Guard stage fails fast before expensive synthesis/repair downstream.
- Non-zero exits surface as `EngineExecutionError`.

### Pattern E: Explicit transform pinning (API-level)

When boundary behavior is compliance-critical, predefine the bridge explicitly.

```python
from morphism.core.node import FunctorNode
from morphism.core.schemas import Int_0_to_100, Float_Normalized

pinned_bridge = FunctorNode(
    input_schema=Int_0_to_100,
    output_schema=Float_Normalized,
    executable=lambda x: x / 100.0,
    name="Pinned_Normalizer",
)
```

Behavior:

- Avoids runtime synthesis for that boundary.
- Keeps transform logic reviewable and deterministic.

## Advanced Composition Patterns

Morphism 3.1.x natively supports linear and fan-out DAGs. Fan-in and conditionals are implemented via composition patterns.

### Conditional branch and guard patterns

No first-class `if/else` syntax exists. Use one of these:

1. Guard-and-fail pattern: stage exits non-zero to abort flow.
2. Guard-and-route pattern: emit tagged payload then route in downstream native command.

Example route pattern:

```text
echo '{"score":85}' | python -c "import sys,json; d=json.load(sys.stdin); print('ok:'+str(d['score']) if d['score']>=0 else 'drop')" | python -c "import sys; x=sys.stdin.read().strip(); print(x.split(':',1)[1] if x.startswith('ok:') else 0)" | render_float
```

### Fan-in (merge) workaround

No native DAG merge operator is implemented. Practical fan-in patterns:

1. External join stage: branch stages write durable outputs (files/queue/topic), then run a separate Morphism pipeline to merge.
2. In-process API orchestration: run branch pipelines independently, merge results in Python, re-enter Morphism as a new source node.

### Nested/subshell integration

Encapsulate complex shell logic in a single native stage:

```text
python -c "import subprocess, json; out=subprocess.check_output('echo 85', shell=True, text=True).strip(); print(json.dumps({'score': int(out)}))" | render_float
```

Guideline: use nested commands to reduce parser ambiguity around shell metacharacters.

### Eight end-to-end examples (increasing complexity)

#### Example 1: Minimal typed bridge

- Initial pipeline: `emit_raw | render_float`
- Detected issue: `Int_0_to_100 -> Float_Normalized` mismatch.
- Applied transform strategy: synthesize scalar normalization bridge.
- Verification outcome: Z3 UNSAT on counterexample query; bridge accepted.
- Final resilient pipeline: `emit_raw -> AI_Bridge_Functor -> render_float`

#### Example 2: Native JSON to typed renderer

- Initial pipeline: `echo '{"score":85}' | render_float`
- Detected issue: inferred `JSON_Object` from native stage, consumer expects `Float_Normalized`.
- Applied transform strategy: synthesize JSON extraction + normalization lambda.
- Verification outcome: accepted if output stays within `0.0..1.0`; otherwise retried/rejected.
- Final resilient pipeline: `echo ... -> AI_Bridge_Functor -> render_float`

#### Example 3: Plaintext numeric boundary

- Initial pipeline: `echo 50 | render_float`
- Detected issue: inferred `Plaintext -> Float_Normalized` mismatch.
- Applied transform strategy: synthesize parse+normalize bridge.
- Verification outcome: accepted only if proof gate can enforce target bound semantics.
- Final resilient pipeline: `echo 50 -> AI_Bridge_Functor -> render_float`

#### Example 4: Fan-out with independent repairs

- Initial pipeline: `echo 50 |+ (render_float, render_float)`
- Detected issue: each branch sees `Plaintext -> Float_Normalized` mismatch.
- Applied transform strategy: resolve each branch edge independently (cache may collapse repeat work).
- Verification outcome: per-edge pass required.
- Final resilient pipeline: `echo 50 -> AI_Bridge_Functor -> render_float` and `echo 50 -> AI_Bridge_Functor -> render_float`

#### Example 5: Guarded JSON extraction

- Initial pipeline: `echo '{"score":85}' | python -c "...assert..." | render_float`
- Detected issue: guarded stage output still mismatched to `render_float` input.
- Applied transform strategy: guard for schema sanity, then synthesize bridge at numeric boundary.
- Verification outcome: guard failures abort early; successful runs must still pass Z3 gate.
- Final resilient pipeline: `echo -> guard -> AI_Bridge_Functor -> render_float`

#### Example 6: Conditional routing via tagged payload

- Initial pipeline: `echo '{"score":-1}' | route_stage | render_float`
- Detected issue: negative/invalid branch should not reach strict consumer.
- Applied transform strategy: route stage emits default-safe value when invalid.
- Verification outcome: bridge verified against routed payload schema.
- Final resilient pipeline: `source -> route_guard -> AI_Bridge_Functor -> render_float`

#### Example 7: Fan-in via external merge step

- Initial pipeline: `emit_raw |+ (python -c "...write a...", python -c "...write b...")`
- Detected issue: no in-engine merge operator for branch convergence.
- Applied transform strategy: external merge command reads branch artifacts and emits unified payload for second pipeline.
- Verification outcome: second pipeline boundaries verified as usual.
- Final resilient pipeline: `branch pipeline` + `merge pipeline` chained operationally.

#### Example 8: Hot-path deterministic rerun

- Initial pipeline: `emit_raw | render_float` executed repeatedly in batch.
- Detected issue: cold run synthesis latency dominates first execution.
- Applied transform strategy: warm cache and reuse verified transform entry.
- Verification outcome: cached code is recompiled and re-verified before execution.
- Final resilient pipeline: warm-path execution with stable bridge reuse and reduced latency.

## Verification Strategies in Pipelines

### Stage-level vs end-to-end verification

Stage-level (current engine behavior):

- Verifies each synthesized boundary transform individually.
- Fast localization of failures.
- Does not prove whole-pipeline semantic properties across multiple stages.

End-to-end (recommended for critical workflows):

- Add explicit postcondition stages and assertions after the full pipeline.
- Combine stage-level Morphism verification with domain-level integration tests.

### Proof granularity and performance trade-offs

- Fine-grained per-edge verification gives precise failure isolation but increases per-boundary overhead.
- Coarser boundaries (manual transforms between grouped stages) reduce synthesis calls but broaden blast radius when wrong.

### Forcing explicit transformations at critical boundaries

Recommended for compliance-critical paths:

1. Introduce pinned bridge nodes in API composition.
2. Limit synthesis to non-critical exploratory boundaries.
3. Keep pinned transforms in version-controlled modules with tests.

### Schema pinning for stability

Schema pinning pattern:

- Use explicit `FunctorNode(input_schema=..., output_schema=...)` definitions for known stages.
- Avoid relying solely on inferred `Pending` transitions in hot production paths.

## Performance + Reliability Tuning

### High-throughput handling

Current runtime is payload-materializing, not streaming-chunked. To scale:

1. Keep per-stage payload compact.
2. Prefer typed JSON summaries over raw large text blobs.
3. Parallelize independent branches with `|+` where semantics allow.

### Cache-aware composition

- Group workflows so repeated schema boundaries recur (improves cache hit rate).
- Pre-warm critical boundaries in deployment smoke runs.
- Clear cache intentionally during model/schema upgrades.

### Avoiding repeated synthesis in hot paths

1. Prefer explicit pinned transforms for fixed, high-frequency boundaries.
2. Reuse stable schema names and contracts.
3. Reduce variability in inferred source formats (normalize upstream output shape).

### Reliability controls

Partial failure handling:

- Any failing node raises and stops the active execution path.
- In fan-out, a failing awaited branch fails the gather result for that execution.

Fallback transforms:

- Built-in fallback is retrying synthesized candidates; no automatic static fallback transform is injected.
- Implement explicit fallback logic as guard/route native stages when required.

Retry boundaries:

- Synthesis retries are bounded by `MORPHISM_MAX_SYNTHESIS_ATTEMPTS`.
- Network retries in synthesizer are bounded and backoff-based.

Idempotent stage design:

- Treat native command stages as potentially side-effectful.
- For retry safety, design stages to be replay-safe (idempotent writes, unique transaction keys, or append-only logs).

## Observability + Debugging

### Per-stage tracing

Use:

1. `MORPHISM_LOG_LEVEL=DEBUG`
2. REPL `history` to inspect actual node chain.
3. REPL `inspect <n>` for stage schema and output snapshot.

### Artifact inspection

- Transform cache DB: `.morphism_cache.db`
- Runtime log file: `logs/morphism.log`

Inspect cached transforms:

```bash
python -c "import sqlite3; c=sqlite3.connect('.morphism_cache.db'); rows=c.execute('SELECT source_name,target_name,lambda_string,timestamp FROM functors').fetchall(); c.close(); print(rows)"
```

Inspect recent diagnostics:

```bash
tail -n 100 logs/morphism.log
```

Windows PowerShell equivalent:

```powershell
Get-Content logs\morphism.log -Tail 100
```

### Root-cause diagnostics for failed transformations

Triage by failure class:

1. `SchemaMismatchError`: boundary unrepaired (often no LLM client or unresolved runtime mismatch).
2. `SynthesisTimeoutError`: model endpoint, timeout, or response-shape issue.
3. `VerificationFailedError`: candidate transform unsafe or unverifiable within constraints/time budget.
4. `EngineExecutionError`: subprocess failure, bridge execution exception, or node runtime exception.

## Security Considerations

### Controlling generated transform execution

- Generated transform code is executed in-process after `eval`.
- Verification gate enforces type/constraint safety, not full behavioral sandboxing.
- For sensitive environments, require one or more of:
  1. pinned transforms at critical boundaries,
  2. restricted model endpoint/network policies,
  3. isolated execution worker for transformation runtime.

### Policy constraints

Recommended policy envelope:

- Allow synthesis only for pre-approved schema pair allowlist.
- Block synthesis for sensitive domains; require reviewed pinned transforms.
- Persist and audit accepted transform artifacts from cache.

### Sensitive-field handling in streamed data

- Since payloads can traverse logs or subprocesses, redact sensitive fields before boundary crossing.
- Prefer tokenized/surrogate identifiers through Morphism stages.
- Keep secrets/config in environment controls; avoid embedding credentials in native command strings.

### Anti-patterns

1. Over-broad transforms
- Symptom: one generic lambda tries to coerce many unrelated source shapes.
- Risk: unverifiable or brittle behavior.
- Fix: split boundaries and pin explicit transforms.

2. Unstable schema assumptions
- Symptom: relying on inference from noisy native outputs.
- Risk: frequent boundary churn and synthesis instability.
- Fix: normalize upstream format to strict JSON and validate early.

3. Hidden side effects
- Symptom: native stages write external state implicitly.
- Risk: retries duplicate side effects.
- Fix: isolate side effects at dedicated terminal stages with idempotency keys.

## Production Checklist

Pipeline design checklist:

1. Are all critical boundaries explicit (pinned) rather than inferred-only?
2. Are native command outputs normalized to stable formats (prefer JSON)?
3. Is `MORPHISM_LOG_LEVEL` set appropriately for environment (INFO prod, DEBUG triage)?
4. Are synthesis/verification timeouts bounded for your SLA?
5. Is cache lifecycle intentional (warm/cold strategy documented)?
6. Are side-effecting stages idempotent or protected by dedupe keys?
7. Are sensitive fields redacted before crossing transform boundaries?
8. Is failure policy defined per stage (fail-fast, route, or fallback)?
9. Are branch outputs observable and validated, not only final last-leaf return?
10. Are integration tests validating end-to-end postconditions in addition to per-edge proofs?

## Failure Playbook

Use this triage sequence for failed pipelines.

1. Capture context
- Save command string, environment values, and timestamp.
- Snapshot `logs/morphism.log` and cache rows for implicated schema pair.

2. Classify failure domain
- Link-time mismatch, synthesis, verification, or execution.

3. Confirm boundary facts
- Identify actual upstream schema and downstream expected schema from `inspect` output or logs.

4. Decide immediate mitigation
- Retry with increased timeout (temporary), or
- pin explicit transform, or
- add guard/normalization stage upstream.

5. Validate fix under replay
- Re-run failing payload and one known-good payload.
- Ensure no duplicate side effects occurred.

6. Stabilize hot path
- Persist pinned transform or pre-warm cache.
- Add regression test covering exact boundary.

7. Close loop
- Document schema contract and failure signature.
- Update operational runbook with remediation command sequence.
