---
title: Morphism Engine Internal Modules Reference
slug: /internal-modules-reference
description: Module-level reference for contributors and maintainers covering APIs, contracts, lifecycles, invariants, extension boundaries, and debugging entry points.
---

## Architecture Module Map

Morphism has two module trees in this repository:

1. Active runtime/package tree: `src/morphism/*` (stable target for contributors).
2. Legacy parallel tree: `morphism_engine/*` (historical implementation, compatibility/archival value).

Stability levels:

- Stable core: `src/morphism/core`, `src/morphism/ai`, `src/morphism/math`, `src/morphism/cli`, `src/morphism/utils`, `src/morphism/config.py`, `src/morphism/exceptions.py`.
- Legacy/compat: `morphism_engine/*`.

### Module Catalog Table

| Module | Responsibility | Public API Surface | Key Types | Upstream Dependencies | Downstream Consumers | Stability |
|---|---|---|---|---|---|---|
| `morphism.cli.shell` | REPL command handling and parse/planning orchestration | `MorphismShell`, `main`, built-ins `history/inspect/tools/quit` | `MorphismShell`, `TOOL_REGISTRY` | `core.pipeline`, `core.node`, `core.native_node`, `ai.synthesizer`, `config`, `utils.logger` | users, tests (`test_phase6_shell`) | stable |
| `morphism.cli.tui` | Textual UI command entry, telemetry, DAG inspection | `MorphismApp`, `main` | `MorphismApp`, `_PipeSuggester`, `_RichLogHandler` | `core.pipeline`, `core.node`, `core.native_node`, `core.cache`, `ai.synthesizer` | users, tests (`test_phase11_tui`) | stable |
| `morphism.core.pipeline` | DAG orchestration, mismatch resolution, runtime execution traversal | `MorphismPipeline.append/add_branch/execute_all/maps_back/maps_forward` | `MorphismPipeline` | `core.node`, `core.cache`, `ai.synthesizer`, `math.z3_verifier`, `exceptions` | CLI layers, tests | stable |
| `morphism.core.node` | DAG vertex abstraction and execution primitive | `FunctorNode.append_child/execute` | `FunctorNode` | `core.schemas`, `utils.logger` | `core.pipeline`, CLI | stable |
| `morphism.core.native_node` | Native subprocess stage with dynamic schema inference | `NativeCommandNode.from_command/execute` | `NativeCommandNode` | `core.inference`, `core.node`, `exceptions` | `core.pipeline`, CLI | stable |
| `morphism.core.inference` | Output payload classification into schema classes | `infer_schema(data: str) -> Schema` | n/a | `core.schemas`, stdlib `json/csv` | `native_node` | stable |
| `morphism.core.schemas` | Schema primitives and built-in schema instances | `Schema` dataclass + constants | `Schema` | stdlib | all execution/verification modules | stable |
| `morphism.core.cache` | SQLite transform cache for synthesized bridges | `FunctorCache.lookup/store/delete/close` | `FunctorCache` | stdlib `sqlite3/hashlib` | `core.pipeline`, CLI TUI cache ownership | stable |
| `morphism.ai.synthesizer` | Transform synthesis provider abstraction and implementations | `LLMSynthesizer.generate_functor`, `OllamaSynthesizer`, `MockLLMSynthesizer` | `LLMSynthesizer`, concrete synthesizers | `config`, `aiohttp`, `core.schemas`, `exceptions` | `core.pipeline`, tests | stable |
| `morphism.math.z3_verifier` | Formal verification of transform safety | `verify_functor_mapping` | verifier helper funcs, AST translator | `z3`, `config`, `core.schemas`, `exceptions` | `core.pipeline`, tests | stable |
| `morphism.config` | Runtime config source from environment | `MorphismConfig`, `config` singleton | `MorphismConfig` | stdlib `os` | synthesizer, pipeline, CLI startup | stable |
| `morphism.exceptions` | Canonical domain exception taxonomy | exception classes | `MorphismError` family | stdlib | all layers | stable |
| `morphism.utils.logger` | Logging setup and namespaced log access | `setup_logging`, `get_logger` | n/a | stdlib `logging` | all layers/tests | stable |
| `morphism_engine.*` | Previous generation implementation | module-specific | legacy types | legacy dependencies | historical tests/manual inspection | legacy |

## Module-by-Module Reference

### `morphism.cli.shell`

Responsibility:

- Parse REPL lines (`|`, `|+`) and instantiate pipeline nodes.
- Handle user-facing built-ins and error surfacing.

Public API surface:

- `main()` process entrypoint.
- `MorphismShell` class and built-in `do_*` commands.

Inputs/outputs:

- Input: terminal command lines.
- Output: stdout status/result lines; exceptions rendered as user-readable errors.

Key invariants:

- Empty command lines are no-op.
- Every pipeline run uses a fresh `MorphismPipeline` instance.
- Unknown registry commands are delegated to `NativeCommandNode`.

Failure modes:

- `MorphismError` -> `[Morphism] ERROR: ...`
- unexpected exception -> `[Morphism] UNEXPECTED ERROR: ...`

Dependency graph:

- Upstream: user terminal.
- Downstream: pipeline orchestration and node modules.

### `morphism.cli.tui`

Responsibility:

- UI composition, command submission, telemetry sink, DAG tree rendering.

Public API surface:

- `main()`, `MorphismApp`.

Inputs/outputs:

- Input: command text from `#cmd-input` widget.
- Output: telemetry pane messages, DAG tree state, inspector details.

Key invariants:

- `@work(exclusive=True)` ensures one active pipeline execution at a time per app instance.
- Input is disabled during active execution and re-enabled in `finally`.

Failure modes:

- `EngineExecutionError` -> “Process Failed”.
- `MorphismError` -> “Pipeline Error”.
- generic exception -> “Unexpected Error” + traceback logging.

Concurrency assumptions:

- UI thread drives widgets; worker executes async pipeline steps.

### `morphism.core.pipeline`

Responsibility:

- Graph mutation (`append`, `add_branch`).
- Schema boundary enforcement and repair (`_resolve_mismatch`).
- Runtime traversal (`execute_all`).

Public API surface:

- `append(new_node)`, `add_branch(parent, children)`, `execute_all(initial_data)`.
- convenience properties: `head`, `tail`, `length`.

Key internal data structures:

- `root_nodes: list[FunctorNode]`
- `all_nodes: list[FunctorNode]`
- `current_context: Optional[FunctorNode]`
- `cache: FunctorCache`

Inputs/outputs:

- Input: DAG nodes, initial payload.
- Output: last-leaf result (compat behavior) + per-node `output_state`.

Invariants:

- Edge compatibility required unless verified bridge inserted.
- Cached bridge is never trusted without compile + verify pass.
- Deferred `Pending` schema edges are resolved at execution-time.

Retry/cancellation boundaries:

- Candidate generation retries bounded by `config.max_synthesis_attempts`.
- No pipeline-global cancellation token or timeout currently.

Failure modes:

- `SchemaMismatchError` when no LLM/repair path.
- `VerificationFailedError` when synthesis+verification exhausts attempts.
- `EngineExecutionError` for node/bridge runtime exceptions.

### `morphism.core.node`

Responsibility:

- Represent a typed DAG transformation step.

Public API:

- `append_child(child)`, `execute(data)`.

Invariants:

- Parent/child links are bidirectional and idempotent.
- `output_state` stores latest execution output.

Thread/process safety:

- Mutable instance state; not thread-safe for concurrent mutation.

### `morphism.core.native_node`

Responsibility:

- Run OS subprocess command and infer output schema.

Public API:

- `from_command(cmd)`, `execute(data)`.

Inputs/outputs:

- Input: command string and optional upstream payload as stdin bytes.
- Output: decoded stdout string with inferred `output_schema`.

Invariants:

- Starts with `Pending` in/out schemas.
- Resolves `output_schema` after successful command execution.

Failure modes:

- Launch failure or non-zero return -> `EngineExecutionError` including stderr details.

### `morphism.core.inference`

Responsibility:

- Heuristic schema classification of text payload.

Public API:

- `infer_schema(data: str)`.

Decision order invariant:

1. JSON object/array -> `JSON_Object`
2. CSV-like multiline with approved delimiter -> `CSV_Data`
3. fallback -> `Plaintext`

Failure behavior:

- JSON/CSV parse failures are non-fatal; function falls through to next heuristic.

### `morphism.core.schemas`

Responsibility:

- Define immutable schema contracts.

Public API:

- `Schema` dataclass and built-in instances (`Int_0_to_100`, `Float_Normalized`, etc.).

Invariants:

- Schema equality is value-based (`dataclass(frozen=True, eq=True)`).
- Constraint strings are consumed by verifier/parser conventions.

### `morphism.core.cache`

Responsibility:

- Persistent mapping from schema-pair to lambda transform string.

Public API:

- `lookup`, `store`, `delete`, `close`, context manager methods.

Storage contract:

- SQLite WAL mode table `functors(schema_hash PK, source_name, target_name, lambda_string, timestamp)`.
- Default DB path: `.morphism_cache.db` in current working directory.

Invariants:

- Keying is deterministic SHA-256 over `"source::target"`.
- Writes are idempotent via `INSERT OR REPLACE`.

Thread/process safety:

- Single connection per cache instance; cross-process coordination delegated to SQLite locking semantics.

### `morphism.ai.synthesizer`

Responsibility:

- Produce candidate lambda strings for schema mismatch repair.

Public API:

- `LLMSynthesizer.generate_functor(source, target)` (abstract).
- `OllamaSynthesizer`, `MockLLMSynthesizer`.

Lifecycle:

- Build prompt with schema metadata and constraints.
- Send request to backend with timeout and network retries.
- Sanitize raw model output to first lambda expression.

Failure modes:

- HTTP/timeout/key extraction failures -> `SynthesisTimeoutError` (after retries).

Determinism notes:

- `MockLLMSynthesizer` supports deterministic test paths.
- Live model path is nondeterministic by nature.

### `morphism.math.z3_verifier`

Responsibility:

- Enforce transform safety via symbolic checks and runtime guards.

Public API:

- `verify_functor_mapping(source_schema, target_schema, transformation_logic, code_str=None, cfg=None)`.

Guarantees:

- For supported numeric constraints, returns `True` only when no violating model exists.
- For non-numeric constraints, executes runtime postcondition checks.

Invariants:

- Dry-run guard executes candidate with schema-appropriate dummy inputs before SMT path.
- `unsat` => safe, `sat` => unsafe, `unknown` => error.

Failure modes:

- `VerificationFailedError` on solver unknown/timeout conditions.
- `False` return for unsafe/counterexample cases.

### `morphism.config`

Responsibility:

- Single immutable config snapshot from env + defaults.

Public API:

- `MorphismConfig`, module singleton `config`.

Invariants:

- Config object is frozen after creation.
- Integer env vars must parse correctly.

### `morphism.exceptions`

Responsibility:

- Shared error taxonomy across modules.

Public API:

- `MorphismError`, `SchemaMismatchError`, `SynthesisTimeoutError`, `VerificationFailedError`, `EngineExecutionError`.

Propagation model:

- Lower layers raise typed errors; CLI layers convert them to user-facing diagnostics.

### `morphism.utils.logger`

Responsibility:

- Initialize logger tree and sinks.

Public API:

- `setup_logging(level)`, `get_logger(name)`.

Invariants:

- setup is idempotent via `_CONFIGURED` guard.
- File sink target: `logs/morphism.log`.

### `morphism_engine.*` (legacy)

Responsibility:

- Prior generation runtime architecture (DLL pipeline model, older shell).

Contributor guidance:

- Do not add new production behavior here.
- Use only for migration reference and historical comparison.

## Contracts and Invariants

### Data Contract Matrix

| Producer Module | Output Contract | Consumer Module | Required Assumptions |
|---|---|---|---|
| CLI parser (`cli.shell`/`cli.tui`) | ordered node segments / branch group | `core.pipeline` | valid segmentation; node objects constructed |
| `core.native_node` | stdout string + inferred `Schema` | `core.pipeline` | process success or typed `EngineExecutionError` |
| `ai.synthesizer` | lambda string candidate | `core.pipeline` | lambda extractable/sanitizable |
| `math.z3_verifier` | boolean safety verdict or typed error | `core.pipeline` | schema constraints interpretable by verifier path |
| `core.cache` | cached lambda string or miss | `core.pipeline` | key determinism and DB accessibility |
| `core.pipeline` | final result + node states | CLI/TUI | last-leaf return semantics accepted |

### Interaction Sequence (request lifecycle through modules)

1. CLI receives command line.
2. CLI parser splits into linear/branch expressions and builds nodes.
3. Pipeline append/add checks schema boundaries.
4. On mismatch: cache lookup.
5. On cache miss/fail: synthesizer generates candidate.
6. Candidate compile/eval in pipeline context.
7. Verifier validates candidate.
8. On pass: bridge node inserted; cache store.
9. Execution starts from roots; branches run via `asyncio.gather`.
10. Native nodes execute subprocess + inference.
11. Runtime deferred mismatch can trigger same resolve path.
12. Result returned; CLI/TUI renders output and diagnostics.

### Invariants + Guarantees

1. No mismatched edge is executed without compatibility or verified bridge.
2. Cached transforms are revalidated before use.
3. Node parent/child graph links remain bidirectionally consistent.
4. Execution errors are wrapped in typed domain exceptions.
5. Logger setup is idempotent.

### Error propagation model

- Module-level errors bubble up as typed exceptions.
- CLI/TUI convert typed errors into user-readable messages and keep session alive.
- Unexpected errors are logged with traceback in debug path.

### Retry and cancellation boundaries

- Synthesis transport retries are local to synthesizer implementation.
- Candidate retries are local to pipeline mismatch resolver.
- No unified cancellation orchestration across pipeline and subprocess steps in current runtime.

## Extension and Integration Guide

### Extension Playbook

How to add a new module safely:

1. Place domain logic under `src/morphism/<layer>/` consistent with responsibility:
- orchestration in `core`
- provider adapters in `ai`/`math`/`core`
- interfaces in `cli`

2. Define explicit contract:
- typed input/output
- error taxonomy mapping to `morphism.exceptions`
- invariants and state ownership

3. Wire via dependency injection where possible (e.g., pipeline constructor args for synthesizer/cache).

4. Add tests in `tests/` phase-aligned style, including failure path assertions.

How to swap adapters/providers:

- Synthesis provider: implement `LLMSynthesizer` and inject into `MorphismPipeline`.
- Cache provider: provide cache object with `lookup/store/delete` semantics.
- Inference path: replace/wrap `infer_schema` and/or `NativeCommandNode` behavior.

Compatibility boundaries:

- Preserve `MorphismPipeline` and `FunctorNode` contracts unless coordinated migration.
- Preserve exception class semantics for caller compatibility.
- Keep schema names stable when cache reuse behavior matters.

### Contributor-safe workflows

Where to place new code:

- runtime core behavior: `src/morphism/core`
- backend integrations: `src/morphism/ai` or `src/morphism/math`
- CLI UX only: `src/morphism/cli`
- diagnostics/logging helpers: `src/morphism/utils`

Naming conventions:

- module names: lowercase with underscores
- exceptions: `*Error` suffix under `morphism.exceptions`
- schema constants: `Pascal_Snake` existing style (e.g., `Float_Normalized`)

Anti-patterns that break guarantees:

1. Bypassing verifier before bridge insertion.
2. Catching and suppressing `VerificationFailedError` in core layers.
3. Mutating schema objects in place (they are intended immutable).
4. Returning non-deterministic outputs from pinned deterministic test adapters.
5. Adding side effects in synthetic bridge code paths without explicit policy.

## Testing and Validation

### Testing Strategy per module type

| Module Type | Required Tests | Suggested Files |
|---|---|---|
| Core orchestration (`core.pipeline`) | append/add behavior, mismatch resolution, runtime deferred mismatch, branch traversal, cache hit/miss | `tests/test_phase9_10.py`, new `test_pipeline_*` |
| Node types (`core.node`, `core.native_node`) | execution semantics, parent/child integrity, subprocess success/failure, stdin passthrough | `tests/test_phase8_native.py` |
| Inference/verification | heuristic classification, numeric proof pass/fail, unknown/timeout behavior | `tests/test_phase8_native.py`, phase verifier tests |
| Synthesis adapters | output sanitization, retry behavior, timeout handling, deterministic mock parity | synthesis-focused tests + integration tests |
| CLI shell | parse grammar, built-ins, error rendering, graceful interrupts | `tests/test_phase6_shell.py` |
| TUI | widget composition, command submission, telemetry integration, disabled input during execution | `tests/test_phase11_tui.py` |

Contract test requirements (minimum):

1. Success-path behavior.
2. Failure-path behavior with exact exception type.
3. Deterministic path (mock adapter or fixed seed behavior).
4. Regression test for previously fixed bug signature.

Profiling hooks and hot paths:

- Hot paths: `_resolve_mismatch`, verifier invocation, native subprocess execution.
- Use logger timestamps and stage-specific debug lines first.
- For deeper profiling, instrument wrapper timers around synthesis/verification/execute segments.

Reliability assumptions:

- Single-process async event loop model.
- TUI enforces one active pipeline task per app instance.
- SQLite cache is local-file backed; cross-process contention delegated to SQLite.

## Failure Analysis and Debugging

### Common Failure Signatures + debugging entry points

| Signature | Likely Module | First Debug Entry Point | Typical Fix |
|---|---|---|---|
| `TYPE MISMATCH: Cannot pipe ...` | `core.pipeline.append` | boundary schemas in CLI `inspect` / logs | add compatible stage or enable/adjust synthesis path |
| `Runtime schema mismatch: ... (no LLM client)` | `core.pipeline.execute_all` | check deferred `Pending` resolution and llm_client wiring | inject synthesizer or pin explicit bridge |
| `Ollama synthesis failed after ... retries` | `ai.synthesizer` | endpoint/model config and network logs | fix URL/model, adjust timeout |
| `Functor F(... ) failed verification ...` | `math.z3_verifier` via pipeline | inspect candidate code and constraints | simplify/guard transform or pin explicit transform |
| `Command '<cmd>' exited with code ...` | `core.native_node` | subprocess stderr and command quoting | fix command path/quoting/permissions |
| `Cached lambda failed verification ... evicting` | `core.cache` + verifier | inspect cache row and rerun mismatch | allow re-synthesis; clear stale DB entries |
| TUI stuck input state | `cli.tui` | `_execute_pipeline` finally path and worker errors | ensure exception paths re-enable input |

Debugging entry points by layer:

- CLI parse: `morphism.cli.shell.MorphismShell.default`
- planning/orchestration: `morphism.core.pipeline.append/add_branch/execute_all`
- synthesis path: `morphism.core.pipeline._resolve_mismatch`, `morphism.ai.synthesizer.OllamaSynthesizer.generate_functor`
- verification path: `morphism.math.z3_verifier.verify_functor_mapping`
- native runtime path: `morphism.core.native_node.NativeCommandNode.execute`
- cache path: `morphism.core.cache.FunctorCache.lookup/store/delete`

Operational triage sequence:

1. Enable DEBUG logs (`MORPHISM_LOG_LEVEL=DEBUG`).
2. Reproduce with minimal pipeline expression.
3. Identify failing boundary (source schema -> target schema).
4. Verify whether failure is synthesis, verification, or runtime.
5. If cache involved, inspect and optionally clear `.morphism_cache.db`.
6. Add/update targeted test before modifying core behavior.

## Contributor Notes

1. Treat `src/morphism/*` as the only authoritative runtime tree for new development.
2. Maintain typed exception contracts; do not leak raw backend exceptions across module boundaries.
3. Keep synthesized-code safety boundary intact: compile -> verify -> insert.
4. Preserve backward-compatible CLI behavior unless a versioned migration plan is provided.
5. When changing schema names or verifier semantics, document cache and compatibility impact explicitly.
