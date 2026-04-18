---
title: Morphism Engine Architecture
description: System architecture specification covering runtime topology, trust boundaries, extensibility, and operational behavior for contributors and platform teams.
slug: /architecture
---

## Architecture at a Glance

Morphism Engine is a typed DAG execution runtime with adaptive boundary repair.

Topology (logical):

1. CLI Entrypoints
2. Parser and Planner (linear and branched DAG assembly)
3. Inference Engine (native output to schema)
4. Synthesis Subsystem (LLM transform generation)
5. Verification Subsystem (Z3 proof gate)
6. Async Execution Runtime (node traversal and fan-out)
7. Cache and Storage (SQLite transform cache)
8. Telemetry and Logging (console, TUI, file)

Primary execution invariant:

- Every edge must satisfy schema compatibility (`producer.out == consumer.in`) or be repaired by injecting a verified bridge node.

Runtime topology to implementation modules:

| Topology Node | Implementation Modules | Runtime Type | Primary Responsibility |
|---|---|---|---|
| CLI entrypoint | `src/morphism/cli/shell.py`, `src/morphism/cli/tui.py` | sync shell, async worker in TUI | accept command text and initiate pipeline execution |
| Parser/planner | CLI parse logic + `src/morphism/core/pipeline.py` | sync parse + async graph mutation | tokenize `|` and `|+`, construct DAG, detect boundaries |
| Inference engine | `src/morphism/core/native_node.py`, `src/morphism/core/inference.py` | async subprocess + sync inference | resolve `Pending` schema from captured stdout |
| Synthesis subsystem | `src/morphism/ai/synthesizer.py` | async HTTP/retry | generate lambda transform candidates |
| Verification subsystem | `src/morphism/math/z3_verifier.py` | sync SMT solve | reject unsafe candidates via counterexample check |
| Execution runtime | `src/morphism/core/node.py`, `src/morphism/core/pipeline.py` | async traversal | execute nodes and propagate outputs through DAG |
| Cache/storage | `src/morphism/core/cache.py` | sync SQLite WAL | persist and reuse verified transforms |
| Telemetry/logging | `src/morphism/utils/logger.py` + TUI RichLog bridge | sync logging | expose diagnostics to console/UI/file |

## Component Model

### Component responsibilities, interfaces, and ownership

| Component | Owned By | Stable Contract | Input | Output | Stability Expectation |
|---|---|---|---|---|---|
| `FunctorNode` | core runtime | `execute(data)`, `append_child`, schema fields | Python object payload | Python object payload and `output_state` | High: core node contract should remain stable |
| `NativeCommandNode` | native adapter layer | `from_command`, overridden `execute` | shell command string + optional stdin | stdout text + inferred schema | Medium: inference heuristics may evolve |
| `MorphismPipeline` | orchestration layer | `append`, `add_branch`, `execute_all` | node graph and optional LLM client | final leaf value + graph state | High: central orchestration API |
| `LLMSynthesizer` | synthesis abstraction | `generate_functor(source, target)` | source/target schemas | lambda code string | High: interface intended for pluggability |
| `verify_functor_mapping` | verification engine | pure function over schemas and callable | source/target schemas + transform | bool or verification exception | High: safety boundary contract |
| `FunctorCache` | persistence layer | `lookup`, `store`, `delete`, context manager | schema pair and lambda string | cache hit/miss + persisted mapping | Medium-high: table schema may evolve with migration strategy |
| config singleton | configuration layer | env-derived immutable fields | process env vars | runtime settings | Medium: additive fields expected |
| logging setup | observability layer | one-time handler install | desired log level | console + file handlers | High: operational contract |

### Contract boundaries

- CLI parse output contract: command text -> sequence/branch of node instances.
- Orchestration contract: no edge executes unless schema is compatible or repaired.
- Synthesis contract: produces code candidate; does not imply safety.
- Verification contract: final safety admission gate for transform insertion.
- Cache contract: keyed reuse by schema names; cached code is re-verified before trust.

## Data/Control Flow

### Command lifecycle sequence

1. CLI receives command text.
2. Parser identifies linear (`|`) or branched (`|+ (...)`) topology.
3. Planner resolves known tools to typed `FunctorNode`; unknown commands become `NativeCommandNode` with `Pending` schemas.
4. Pipeline `append`/`add_branch` performs compile-time boundary checks where possible.
5. On mismatch with LLM configured:
   - cache lookup by schema pair hash;
   - if miss, synthesize candidate;
   - compile candidate and verify;
   - inject `AI_Bridge_Functor` on pass.
6. Runtime executes roots and traverses children via `asyncio.gather` fan-out.
7. Runtime resolves deferred `Pending` boundaries after native node inference.
8. Runtime may perform additional mismatch repair at execution-time.
9. Final leaf result is returned; node outputs remain in graph state for inspection.

### Synchronous vs async boundaries

| Boundary | Mode | Notes |
|---|---|---|
| CLI shell loop | sync | wraps async work with `asyncio.run` |
| TUI command processing | async worker | `@work(exclusive=True)` serializes command execution per app instance |
| Native subprocess execution | async | uses `asyncio.create_subprocess_shell` |
| Synthesis HTTP call | async | aiohttp request with timeout and retries |
| Verification | sync | Z3 solver invoked synchronously with timeout |
| Cache operations | sync | SQLite operations in-process |

### Retry/recovery behavior

- Synthesis network-level retries: up to 3 with exponential backoff in synthesizer implementation.
- Candidate-level retries: up to `MORPHISM_MAX_SYNTHESIS_ATTEMPTS` in pipeline resolver.
- Cache recovery:
  - cached code compile failure -> bypass cache and regenerate;
  - cached code verification failure -> delete cache entry and regenerate.

### Timeout and cancellation propagation

- LLM request timeout: `MORPHISM_LLM_REQUEST_TIMEOUT` (aiohttp client timeout).
- Z3 timeout: `MORPHISM_Z3_TIMEOUT_MS` (`solver.set("timeout", ...)`).
- Pipeline-level global timeout/cancellation token: not currently implemented.
- TUI cancellation semantics: exclusive worker serializes execution; explicit cancellation API is not exposed in current implementation.

## Trust + Security Boundaries

### Untrusted inputs

- User command text.
- Native subprocess outputs (arbitrary bytes decoded to text).
- LLM responses (code strings).
- Environment-provided configuration values.

### Generated code handling

- Candidate transforms are evaluated via `eval` and only accepted after verification checks.
- Eval globals include `__builtins__`, `json`, `math`, `re`; this enables expressive transforms but expands attack surface.
- Verification proves value-domain safety properties, not general non-malicious behavior.

### Verification gate as safety boundary

- Gate enforces schema postcondition preservation and catches many unsafe transforms.
- Gate is necessary but not sufficient as a full sandbox/security boundary.
- Additional hardening for enterprise contexts should include:
  - constrained evaluator/sandbox,
  - policy checks on AST shape,
  - restricted builtins and side-effect controls.

### Secrets/config handling model

- Configuration sourced from process environment (`MORPHISM_*` variables).
- No dedicated secret manager integration in current runtime.
- Sensitive values should be injected externally (CI secrets manager, platform env controls) and never logged.

### Trust boundary map

| Boundary | Trusted Side | Untrusted Side | Control Mechanism |
|---|---|---|---|
| CLI input boundary | runtime internals | user command text | parser constraints + typed graph checks |
| Native process boundary | runtime internals | subprocess command/stdout/stderr | subprocess exit-code handling + inference fallback |
| LLM boundary | runtime internals | generated lambda code | compile check + verification gate + retries |
| Cache boundary | persisted local data | potentially stale/poisoned local entries | recompile + reverify + eviction on failure |

## Deployment Models

### Local-only development

- Typical mode: shell or TUI, local Ollama endpoint, local SQLite cache.
- Strongest observability surface (interactive inspection, RichLog, file logs).

### CI model

- Prefer non-interactive shell-like invocation paths.
- Use deterministic synthesizer substitute for tests (`MockLLMSynthesizer`) where reproducibility is required.
- Pin timeout and attempt env vars for bounded runtime behavior.

### Enterprise private infrastructure

- Private model endpoint via `MORPHISM_OLLAMA_URL`.
- Managed package and artifact sources.
- Platform controls should enforce process isolation and least privilege around native command execution.

### Constrained/offline environments

- Core DAG + verification + cache remain functional without network if synthesis is not required or deterministic local synthesizer is used.
- Full adaptive repair with remote model is degraded when LLM endpoint is unavailable.

## Extensibility Model

### Plugin/adapter points

1. LLM backend replacement via `LLMSynthesizer` subclass.
2. Custom schema catalog extension in `core/schemas.py`.
3. Inference strategy replacement by wrapping/replacing `infer_schema` and/or `NativeCommandNode` execution behavior.
4. Cache backend replacement by implementing cache-like lookup/store/delete contract.
5. CLI registry extension by adding entries to tool registry constructors.

### Custom schema handlers

- Existing constraints parser is optimized for bounded numeric constraints.
- New schema families should define:
  - canonical `name`, `data_type`, `constraints` representation,
  - verifier translation strategy or explicit runtime-only validation policy.

### Policy hooks

Current hooks are implicit via replacement/subclassing. Recommended explicit hook surfaces for near-term extension:

- pre-eval policy hook (AST allowlist)
- post-verification admission policy
- per-command execution authorization policy
- cache-admission policy

### Module replacement strategy

- Preferred pattern: dependency injection at pipeline construction (LLM client and cache object).
- Secondary pattern: module-level function replacement for inference/verification adapters in controlled builds.

## Observability + Operations

### Structured logging surfaces

- Console logs: `[LEVEL] message` at configured level.
- File logs: timestamped DEBUG stream at `logs/morphism.log`.
- TUI telemetry: RichLog sink bridged from `morphism` logger.

### Proof and transform artifacts

- Transform cache artifact: `.morphism_cache.db`.
- Proof certificate artifacts: JSON transcripts written under `logs/proofs` (configurable via `MORPHISM_PROOF_CERT_DIR`).

### Debug traces and health signals

Operational health indicators available now:

- cache hit/miss/store/delete log lines;
- synthesis retry/failure logs;
- verification pass/fail logs;
- subprocess exit-code errors.

Recommended operational health probes:

1. import probe (`morphism`, `z3`)
2. verification probe on known safe transform
3. cache read/write probe in working directory
4. model endpoint reachability probe (if adaptive synthesis enabled)

### Component interaction table

| Caller | Callee | Interaction Type | Criticality | Backpressure/Timeout Control |
|---|---|---|---|---|
| CLI shell/TUI | `MorphismPipeline` | async command execution | critical | TUI worker serialization; no global pipeline timeout |
| Pipeline | Cache | sync lookup/store/evict | high | SQLite timeout 5s |
| Pipeline | Synthesizer | async generation call | high on misses | aiohttp timeout + retry |
| Pipeline | Verifier | sync proof check | critical safety gate | Z3 timeout setting |
| Pipeline | Node execution | async traversal | critical | exception wrapping to `EngineExecutionError` |
| Native node | OS subprocess | async spawn/chunked stream | high | process exit code; no per-command timeout yet |
| Logger | file system/TUI | sync emit | medium | depends on FS and UI responsiveness |

## Performance Architecture

### Cold path vs warm path

Cold path (first mismatch):

- parse -> mismatch detect -> cache miss -> synthesis (dominant) -> compile -> verify -> execute -> store cache

Warm path (repeat mismatch):

- parse -> mismatch detect -> cache hit -> compile -> verify -> execute

Warm path eliminates network/model latency and is typically much faster.

### Cache hit dynamics

- Key granularity: schema pair only (`source_name::target_name`).
- Benefits: maximal reuse for repeated boundary classes.
- Trade-off: no prompt/version/model dimension in key; re-verification mitigates stale-risk but not full provenance concerns.

### Known hotspots

1. LLM generation latency and retry loops.
2. Native subprocess runtime for expensive commands.
3. Large payload schema inference and data marshaling.

### Scaling strategy

Current strategy (single-process):

- async fan-out for branch children;
- local SQLite WAL for low-overhead cache persistence;
- per-command execution lifecycle.

Scale-out opportunities:

- distributed cache service with provenance metadata;
- process isolation pools for native commands;
- verifier offload/parallel proof workers for heavy constraint workloads;
- explicit cancellation and per-node timeout controls.

## Failure Domains + Recovery

Failure-domain map:

| Failure Domain | Trigger | Immediate Effect | Degrades vs Breaks | Recovery Path | Functional Remainder |
|---|---|---|---|---|---|
| CLI parse/planning | malformed command topology | command rejected or misparsed | breaks request | correct syntax; improve parser diagnostics | runtime itself unaffected |
| Native command execution | command not found / non-zero exit | `EngineExecutionError` | breaks affected branch/request | fix command/env; retry | other independent commands still possible |
| Inference ambiguity | non-JSON/non-CSV or ambiguous payload | fallback to `Plaintext` | degrades (may trigger extra synthesis) | emit explicit JSON; custom inference | pipeline continues |
| Synthesis endpoint failure | timeout/network/model error | no candidate generated | degrades to failure on unresolved mismatch | endpoint restore; retries; deterministic synthesizer | already-compatible edges still run |
| Verification failure | SAT counterexample or timeout | candidate rejected | breaks unresolved boundary | retry candidates; adjust schemas; tune timeout | compatible edges still run |
| Cache corruption/staleness | invalid cached code | cache entry rejected/evicted | degrades to synthesis path | auto-evict or clear DB | runtime continues |
| Logging sink failure | file write issues | reduced observability | degrades only | fix FS permissions/path | execution continues |

Recovery principles:

1. Safety before liveness: unverifiable transforms are rejected.
2. Prefer local repair: stale cache entries are evicted automatically.
3. Keep compatible graph segments executable when possible.

## Evolution and Compatibility

### Near-term extension roadmap hooks

1. Explicit parser/planner module separation from CLI frontends.
2. First-class policy engine for transform admission and subprocess authorization.
3. Proof artifact persistence (machine-readable counterexample/proof records).
4. Pluggable cache backends with provenance-aware keys.
5. Per-node timeout/cancellation and lifecycle tracing APIs.

### Compatibility contracts for future modules

Contracts to preserve:

- `LLMSynthesizer.generate_functor(source, target) -> str`.
- Pipeline invariant: no edge executes across schema boundary without compatibility or verified bridge.
- Error taxonomy (`SchemaMismatchError`, `VerificationFailedError`, `EngineExecutionError`) as user-facing semantics.
- `Schema` representation continuity (`name`, `data_type`, `constraints`) with migration notes if parser semantics change.

Contracts that may evolve with migration guidance:

- cache schema/table fields and key composition;
- inference heuristics and confidence metadata;
- branch result API (currently last-leaf compatibility behavior).

Assumptions explicitly annotated:

- Numeric proof path assumes constraints parsable as bounded intervals.
- Verification currently proves value-domain properties, not full side-effect freedom.
- Local SQLite cache is process-local by default and not globally coherent across hosts.
