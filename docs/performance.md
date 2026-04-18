---
title: Performance Internals
slug: /performance
description: Architecture-specific performance guide for optimizing latency, throughput, and cost in Morphism Engine under production load.
---

## Performance Model

Morphism latency is dominated by whether execution stays on the no-mismatch path or enters synthesis and verification.

### Cold Path vs Warm Path

Definitions:

- Warm path: no schema mismatch, or mismatch resolved from cache and passes re-verification immediately.
- Cold path: schema mismatch with cache miss (or stale cache entry), requiring synthesis attempts and verification.

Stage composition for one pipeline execution:

$$
L_{total} = L_{parse} + L_{plan} + \sum_{i=1}^{N} L_{node,i} + \sum_{j=1}^{M} L_{mismatch,j}
$$

For each mismatch boundary:

$$
L_{mismatch} = L_{cache\_lookup} + \mathbb{1}_{hit}L_{cache\_reverify} + \mathbb{1}_{miss}\sum_{k=1}^{A}(L_{synth,k}+L_{compile,k}+L_{verify,k}) + L_{cache\_store}
$$

Where:

- $A$ is accepted attempt index, bounded by MORPHISM_MAX_SYNTHESIS_ATTEMPTS.
- verification includes dry-run checks and symbolic solver/runtime postcondition paths.

### Stage-by-Stage Latency Budget Table

Budgets below are engineering targets for interactive CLI/TUI workloads; tune to your SLO tier.

| Stage | Target p50 | Target p95 | Hard ceiling | Dominant driver | Primary control |
|---|---:|---:|---:|---|---|
| Parse + planning | 1-5 ms | 5-15 ms | 30 ms | command tokenization and DAG assembly | avoid repeated regex and rebuilds |
| Inference (native output schema detection) | 0.1-2 ms | 2-8 ms | 20 ms | JSON parse / CSV sniffer and payload size | bounded sniff window, payload caps |
| Cache lookup (SQLite) | 0.2-2 ms | 2-8 ms | 20 ms | local disk latency and WAL contention | local SSD, short transactions |
| Compile candidate (eval) | 0.1-1 ms | 1-5 ms | 10 ms | expression complexity | sanitize early, reject quickly |
| Verification (numeric SMT) | 2-30 ms | 30-200 ms | MORPHISM_Z3_TIMEOUT_MS | constraint and AST complexity | timeout, expression simplification |
| Verification (runtime fallback for unsupported domains) | 0.1-5 ms | 5-20 ms | 50 ms | callable behavior on sample input | deterministic transforms |
| Synthesis request | 80-600 ms | 600-2500 ms | MORPHISM_LLM_REQUEST_TIMEOUT | model latency and transport | model size, endpoint locality |
| Native command execution | workload dependent | workload dependent | command timeout policy | subprocess runtime and IO | shell command design |
| DAG fan-out coordination | <1 ms/child | <5 ms/child | 20 ms/child | asyncio scheduling and child count | branch width limits |

### Throughput Constraints

Pipeline throughput is bounded by the slowest recurring stage in steady state.

Approximate envelope:

$$
TPS \approx \frac{W}{E[L_{total}]}
$$

Where:

- $W$ is effective parallel workers/pipelines.
- $E[L_{total}]$ is expected latency including miss probability.

Branching behavior:

- Sibling execution uses asyncio gather; branch throughput scales until CPU, subprocess, or LLM/solver bottlenecks dominate.
- Per-boundary synthesis and verification are still serial inside each mismatch loop.

### Memory Profile

Primary memory consumers:

- pipeline graph objects (nodes, parent/child lists, output_state snapshots)
- native command stdout buffers (decoded full text)
- temporary solver AST/expression objects during verification
- telemetry buffers in TUI RichLog

Memory growth risks:

- very large stdout payloads retained in output_state
- long sessions with many DAG nodes and heavy telemetry retention

Practical control points:

- truncate or externalize large payloads in downstream tools
- constrain native command output size
- use bounded session lifetimes for long-running interactive shells

## Stage Cost Breakdown

Cost centers map directly to core modules and call sites.

1. Parse/planning
- Source: command parsing and node construction in shell/TUI command path.
- Cost mode: mostly CPU-bound, low variance.

2. Inference
- Source: infer_schema over native command output.
- Cost mode: payload-size dependent; JSON and CSV heuristics are cheap but not free.

3. Synthesis
- Source: provider call in mismatch resolver.
- Cost mode: highest variance and largest tail latency; dominates cold-path cost.

4. Verification
- Source: verifier dry-run, symbolic encoding (numeric + supported string domains), solver check, runtime fallback for unsupported domains.
- Cost mode: moderate median, high tail under complex expressions or timeout pressure.

5. Execution
- Source: node execute and native subprocess execution.
- Cost mode: user workload dependent; often dominates when commands are heavy.

6. Cache access
- Source: lookup/store/delete against SQLite WAL DB.
- Cost mode: low median; sensitive to disk and concurrent writer pressure.

### Hot Path Analysis

Warm steady-state hot path for mismatched-but-cached boundaries:

1. cache lookup hit
2. candidate compile
3. verifier re-check
4. bridge execute
5. downstream node execute

Cold hot path (worst practical case):

1. cache miss
2. synthesis request
3. compile reject or verifier reject
4. retry loop up to max attempts
5. successful verify and cache store
6. bridge execute and continue

Hot-path bottleneck ordering in production-like load:

1. synthesis request latency and retry amplification
2. solver timeout/complexity for numeric constraints
3. native subprocess IO for command-heavy pipelines
4. cache contention only under heavy concurrency

## Cache and Reuse Dynamics

Cache design summary:

- key: SHA-256 of source_schema_name::target_schema_name
- value: lambda string
- backend: SQLite with WAL mode, lazy-open connection
- trust model: cache hit is recompiled and reverified before use

Hit/miss dynamics:

- hit path removes synthesis cost but retains verification cost
- miss path pays synthesis + verification + optional retries
- stale entries are evicted on compile/verification failure

### Cache Effectiveness Model

Expected mismatch latency:

$$
E[L_{mismatch}] = H\cdot(L_{lookup}+L_{reverify}) + (1-H)\cdot(L_{lookup}+E[L_{cold\_resolve}])
$$

Where:

- $H$ is cache hit rate for schema boundaries.
- $E[L_{cold\_resolve}]$ includes synthesis attempts and final store.

Cold resolve estimate:

$$
E[L_{cold\_resolve}] \approx E[A]\cdot(L_{synth}+L_{compile}+L_{verify}) + L_{store}
$$

Implications:

- Increasing hit rate yields near-linear latency reduction until verification or execution dominates.
- Excess schema-name churn collapses hit rate and shifts cost to synthesis.
- Overly aggressive invalidation improves safety confidence but can increase cold-path spend.

Eviction/invalidation impact:

- automatic invalidation on stale/unsafe cache entries prevents persistent correctness regressions.
- repeated invalidation on same boundary is a strong signal of provider drift or policy change.

## Profiling and Instrumentation

Measure before tuning. Use stage-level timings with stable labels.

What to measure:

- end-to-end latency: p50/p95/p99 by command pattern
- stage latency: parse, inference, lookup, synth, compile, verify, execute
- synthesis attempts per mismatch and acceptance attempt index
- solver outcomes: unsat/sat/unknown and timeout count
- cache metrics: hit rate, stale-evict rate, store rate
- error class rate: synthesis timeout, verification failure, execution error

Where to instrument:

- CLI/TUI command entry and completion around pipeline execution call
- pipeline mismatch resolver around lookup, compile, verify, store
- verifier around dry-run, solver check, runtime postcondition branch
- native node around subprocess launch, communicate duration, output bytes
- cache backend around SQL lookup/store/delete durations

Trace interpretation guidance:

- high verify time with low synth time: solver complexity issue, not model issue
- high synth time with few retries: model or network latency bottleneck
- high miss rate but stable schemas expected: key fragmentation or naming drift
- growing end-to-end latency with stable stage medians: concurrency queueing/saturation

### Profiling Workflow

1. Establish baseline
- run representative command mix and capture stage histograms for at least 1k executions.

2. Segment by path
- split traces into warm/no-mismatch, warm/cached-mismatch, and cold/miss buckets.

3. Identify top contributor
- use cumulative stage time share to locate primary latency and cost center.

4. Apply one controlled change
- adjust a single lever (timeout, model, cache placement, branch width, command IO pattern).

5. Re-measure and compare
- require measurable p95 improvement and no correctness regression signals.

6. Promote with guardrails
- ship behind flag/canary and monitor stale-evict, unknown, and timeout spikes.

## Tuning Strategies

### Solver Performance Tuning

Timeout strategy:

- set MORPHISM_Z3_TIMEOUT_MS to enforce bounded tail latency.
- choose timeout from SLO budget, not from best-case latency.

Constraint complexity controls:

- keep generated transforms within supported AST subset where possible.
- avoid unnecessary nested min/max/cast chains in candidate logic.
- preserve simple numeric bounds syntax to avoid parse failures.

Fallback behavior tuning:

- for unsupported non-symbolic constraints, runtime postcondition path is used; keep sample execution deterministic and cheap.
- if unknown outcomes rise, reduce expression complexity or raise timeout cautiously after profiling.

### Batching and Parallelism Boundaries

What can scale in parallel:

- branch children execution after parent completion via asyncio gather.
- multiple independent pipelines at process level.

What should stay bounded:

- synthesis retries per boundary
- concurrent native subprocess fan-out to avoid host saturation
- concurrent solver-heavy boundaries when CPU is constrained

Practical boundaries:

- cap branch width for command-heavy fan-outs.
- use external queueing for burst loads instead of unbounded in-process parallelism.

### Avoiding Redundant Synthesis

- maximize schema name stability to preserve cache locality.
- reuse canonical boundary mappings across tools.
- prevent accidental schema proliferation for semantically identical domains.
- keep cache persistent on fast local storage for interactive sessions.

### Deterministic Short-Circuiting

- deterministic provider mappings for known hot schema pairs reduce cold-path variance.
- preserve first-admissible acceptance semantics to minimize additional ranking overhead.
- ensure known-safe boundaries are cache-prewarmed when bootstrapping latency-sensitive environments.

### IO Tuning in CLI Pipelines

- minimize oversized stdout in native commands; emit only fields needed by downstream nodes.
- prefer structured JSON output for predictable inference and transform handling.
- avoid shell pipelines that produce large intermediate text blobs when direct command options exist.
- monitor subprocess stderr and non-zero exits as immediate performance and correctness degraders.

## Failure/Degradation Scenarios

1. Synthesis tail-latency spikes
- Signal: p95/p99 drift concentrated in synth stage.
- Likely causes: endpoint contention, larger model, network instability.
- Actions: pin closer endpoint/model, tighten retries/timeouts, increase cache hit rate.

2. Solver timeout storms
- Signal: rising unknown outcomes and verification failures near timeout limit.
- Likely causes: complex generated expressions or under-provisioned CPU.
- Actions: simplify candidate space, tune timeout within SLO, throttle mismatch concurrency.

3. Cache inefficiency regressions
- Signal: hit rate drops, cold resolves increase, cost rises.
- Likely causes: schema naming drift, cache resets, key incompatibility changes.
- Actions: restore stable naming, validate key strategy, persist cache across restarts.

4. Native execution saturation
- Signal: execute stage dominates, queueing in branch-heavy commands.
- Likely causes: expensive subprocesses and large IO.
- Actions: reduce branch fan-out, optimize commands, enforce output size limits.

### Performance Troubleshooting Runbook

1. Confirm symptom bucket
- latency, throughput, or cost regression; identify affected command families.

2. Pull stage metrics
- compare current vs baseline for parse, inference, lookup, synth, verify, execute.

3. Classify path mix
- quantify warm/no-mismatch vs cached mismatch vs cold mismatch proportions.

4. Isolate dominant stage
- select the stage with largest p95 delta and cumulative share.

5. Apply targeted fix
- synthesis bottleneck: provider/endpoint/cache tactics
- verification bottleneck: timeout/complexity tactics
- execution bottleneck: command IO and parallelism tactics
- cache bottleneck: storage and key locality tactics

6. Validate correctness and SLO
- no increase in unsafe acceptance signals, and SLO metrics recover.

7. Roll forward or rollback
- keep change if stable over soak window; rollback quickly if tail or error rates regress.

## Operational Checklist

### SLO-Oriented Tuning Checklist

Use this checklist before enabling a performance change in production-like environments.

- Define SLO targets for p50/p95/p99 latency and minimum throughput.
- Set explicit budgets for synth and verify stages relative to total latency.
- Configure MORPHISM_Z3_TIMEOUT_MS within tail-latency envelope.
- Configure MORPHISM_LLM_REQUEST_TIMEOUT and retry bounds to cap worst-case cold path.
- Confirm cache hit-rate target and monitor stale-evict ratio.
- Validate branch fan-out ceilings for host CPU and subprocess capacity.
- Ensure deterministic CI path for synthesis-sensitive tests.
- Add stage timers and outcome counters before and after changes.
- Run canary with representative load; compare against baseline quantitatively.
- Keep rollback switch and operator runbook updated before broad rollout.
