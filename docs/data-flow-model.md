---
title: Morphism Engine Data Flow Model
description: Systems-level model of data movement, control boundaries, verification gates, and failure semantics in Morphism Engine.
slug: /data-flow-model
---

## End-to-End Flow Overview

Morphism executes a typed pipeline by separating data flow from control flow, then joining them at boundary gates.

Data flow path (payload movement):

`source stage output -> boundary -> (optional bridge) -> next stage -> ... -> final emission`

Control flow path (decision movement):

`parse/plan -> compatibility check -> cache lookup -> synthesize -> verify -> execute/abort`

Formal view:

- Stage output at step `i`: `v_i`
- Stage schema pair: `S_i^out -> S_{i+1}^in`
- Edge is executable iff:

$$
Executable(i) := (S_i^{out} = S_{i+1}^{in}) \lor \exists h_i : S_i^{out} \to S_{i+1}^{in} \text{ with } Verify(h_i)=true
$$

This is the core safety boundary for data motion.

## Stage Contracts

### Stage-by-Stage Flow Table

| Stage | Input Interface | Output Interface | Control Decision | Failure Class | Notes |
|---|---|---|---|---|---|
| 1. Source ingestion | CLI/TUI command text; optional initial data (`None` for source nodes) | Node graph roots (`FunctorNode` / `NativeCommandNode`) | Parse linear vs branch grammar | parse/usage error | Data not yet executed; this is planning surface |
| 2. Boundary detection | Adjacent schemas (`out`, `in`) | direct edge or repair request | equality check (`out == in`) or deferred if `Pending` | `SchemaMismatchError` (if no repair path) | Compile-time when schemas known; runtime when deferred |
| 3. Schema projection/inference | Native stdout string | projected schema (`JSON_Object`, `CSV_Data`, `Plaintext`) | JSON/CSV/fallback heuristic order | subprocess failure -> `EngineExecutionError` | Inference only for native nodes |
| 4. Transform insertion | mismatch pair `(A, B)` | bridge node candidate `h: A -> B` | cache hit/miss; compile candidate | synthesis timeout / compile reject | Bridge is not admitted yet |
| 5. Verification gate | candidate `h`, source/target constraints | admit/reject signal | solver UNSAT/SAT/unknown and runtime guard checks | `VerificationFailedError` or reject-and-retry | Safety gate before bridge executes |
| 6. Execution and emission | executable DAG + payload values | final leaf output + node `output_state` snapshots | async traversal + branch fan-out | `EngineExecutionError` | Output emitted as `>>> ...` (REPL) or telemetry/UI |

### Control flow vs data flow separation

Data flow carries values (`v_i`) through executed nodes.

Control flow carries decisions:

1. Can edge execute directly?
2. Do we need synthesis?
3. Is cached transform valid?
4. Did verifier admit transform?
5. Abort or continue?

Interaction points:

- Boundary check joins control and data schemas.
- Verification outcome controls whether data can cross mismatch edge.
- Runtime `Pending` resolution joins inferred data shape and control checks.

### Buffering/streaming assumptions

Current runtime model is payload-buffered, not streaming-chunked:

- Native stage captures full stdout before inference.
- Upstream output is materialized and then passed to downstream stage.
- Branch children receive parent result after parent stage completes.

Implications:

- Latency: per-stage completion barrier before downstream starts.
- Memory: bounded by largest in-flight payload per active branch.
- Throughput: branch parallelism helps independent edges, but each edge remains payload-buffered.

## Execution Path Variants (cold/warm/failure)

### Cold path (first mismatch, no cache hit)

1. detect mismatch `A != B`
2. cache lookup miss
3. synthesize candidate `h`
4. compile candidate
5. verify candidate
6. insert bridge and execute
7. store bridge in cache

Expected cost profile: synthesis + verification dominate.

### Warm path (cache hit)

1. detect mismatch `A != B`
2. cache lookup hit
3. compile cached code
4. re-verify cached candidate
5. execute with bridge

Expected cost profile: no synthesis round-trip; lower latency.

### Failure path variants

1. Synthesis failure path:
- trigger: backend timeout/unavailable/invalid response
- state: edge unresolved
- outcome: terminal for this pipeline execution

2. Verification rejection path:
- trigger: SAT counterexample or repeated candidate rejection
- state: no admissible bridge
- outcome: terminal for this pipeline execution

3. Runtime stage failure path:
- trigger: subprocess non-zero or stage runtime exception
- state: current execution path aborted
- outcome: terminal for this run

### Lifecycle sequence example (single command chain)

Example chain:

```text
emit_raw | render_float
```

Sequence:

1. Parse creates node A (`emit_raw`) and node B (`render_float`).
2. Boundary check sees `Int_0_to_100 != Float_Normalized`.
3. Resolve mismatch:
- lookup cache for `Int_0_to_100::Float_Normalized`
- if miss, synthesize candidate (for example `lambda x: x / 100.0`)
- verify candidate with solver + guards
4. Insert `AI_Bridge_Functor` between A and B.
5. Execute A -> bridge -> B.
6. Emit final output.

Expected output:

```text
>>> [RENDERED UI]: 0.5
```

## Observability and Debugging

### Observability surfaces

1. Logger stream:
- console logs (level controlled by `MORPHISM_LOG_LEVEL`)
- file logs at `logs/morphism.log`

2. Runtime state:
- node `output_state`
- REPL `history` and `inspect <n>`
- TUI DAG tree + inspector pane + telemetry log

3. Persistence artifacts:
- cache DB `.morphism_cache.db` with accepted bridge code
- no standalone proof transcript file in core 3.1.x (proof outcomes appear in logs)

### Failure-domain map

| Failure Domain | Trigger | Local Effect | Recoverable in-session? | Terminal for run? | Next Debug Step |
|---|---|---|---|---|---|
| Parse/planning | malformed pipeline expression | no executable graph | yes (enter new command) | yes | re-enter minimal expression |
| Boundary mismatch without repair | no LLM/bridge path | edge blocked | yes | yes | inspect schemas and bridge strategy |
| Synthesis transport | endpoint timeout/unreachable | no candidate produced | yes | yes | verify endpoint/model/timeouts |
| Verification rejection | candidate unsafe/unverifiable | candidate dropped | yes (retry candidates until budget) | yes if budget exhausted | inspect constraints and candidate shape |
| Native subprocess failure | command non-zero | node fails | yes | yes | inspect stderr/quoting/path |
| Cached transform invalid | compile/verify fail | entry evicted, cold path resumes | yes | no (if synthesis succeeds) | inspect cache row and policy drift |

### How to debug flow issues playbook

1. Reproduce with smallest failing pipeline expression.
2. Enable debug logging:

```bash
export MORPHISM_LOG_LEVEL=DEBUG
```

3. Identify failing boundary (`source_schema -> target_schema`) from logs/inspect.
4. Determine failure class:
- mismatch/no repair
- synthesis transport
- verification rejection
- runtime stage failure
5. Check cache involvement:

```bash
python -c "import sqlite3; c=sqlite3.connect('.morphism_cache.db'); print(c.execute('select source_name,target_name,lambda_string,timestamp from functors').fetchall()); c.close()"
```

6. If policy or schema changed, clear cache and rerun cold path intentionally.
7. Add/adjust guard stage or pinned transform for unstable boundaries.

## Performance Considerations

### Latency and bottleneck notes

Primary contributors (highest to lowest in typical mismatch runs):

1. synthesis HTTP/model latency
2. verification solver time
3. native subprocess runtime
4. inference/classification overhead
5. cache lookup/write overhead

Cold vs warm expectations:

- Cold mismatch: synthesis + verification + execution.
- Warm mismatch: cache hit + reverify + execution.

Bottleneck implications:

- repeated same schema boundaries benefit strongly from warm cache.
- high-volume native outputs increase buffering and parse costs.

Optimization levers:

1. Normalize upstream payload shape to reduce synthesis ambiguity.
2. Keep critical boundaries stable to maximize cache reuse.
3. Bound solver and request timeouts for predictable SLO behavior.
4. Use branch fan-out only when downstream stages are independent and side-effect-safe.

## Practical Guidance

1. Treat each boundary as a typed contract, not a string pipe.
2. Distinguish data path failures (bad payload) from control path failures (bad candidate/proof).
3. Use warm-cache preflight in production rollouts for known hot boundaries.
4. Introduce explicit guard stages before strict consumers.
5. For critical domains, pin transforms and use synthesis only at non-critical edges.
6. Persist logs and cache artifacts for post-incident flow reconstruction.
