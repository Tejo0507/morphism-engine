---
title: Extending the Engine
slug: /extending-the-engine
description: Contributor-grade extension manual for adding adapters, providers, policies, cache implementations, and observability integrations without violating Morphism correctness guarantees.
---

## Extension Architecture Overview

This guide defines extension work as contract-preserving integration with the active runtime in `src/morphism/*`.

Scope in v3.1.x:

- There is no dynamic plugin loader or registry protocol at runtime.
- Extension points are code-level seams: you implement compatible classes/functions and wire them into composition roots (CLI setup, pipeline construction, app bootstrap).
- Verification is the hard trust boundary for synthesized transforms.

Contributor posture:

- Treat every extension as part of a proof-carrying execution path.
- If your extension can alter type boundaries, transform semantics, or acceptance criteria, it can break safety.
- Maintain deterministic and auditable behavior under failure.

### Extension Surface Matrix

| Surface | Primary Module(s) | Contract Anchor | Lifecycle Entry | Failure Blast Radius | Compatibility Level |
|---|---|---|---|---|---|
| Schema adapters | `morphism.core.schemas`, `morphism.core.inference` | `Schema` value semantics, constraint grammar, inference precedence | schema declaration + inference routing | wrong schema typing, verifier mismatch, unsafe bridge generation | stable with strict invariant adherence |
| Transformation providers | `morphism.ai.synthesizer`, `morphism.core.pipeline` | `LLMSynthesizer.generate_functor` returns executable lambda string | mismatch resolution loop (`_resolve_mismatch`) | compile reject storms, unsafe transforms, timeout amplification | stable abstract interface |
| Verification policy hooks | `morphism.math.z3_verifier`, `morphism.core.pipeline` | `verify_functor_mapping` boolean/error semantics | compile pass -> verifier handoff | unsafe acceptance or false rejection at all mismatch edges | soft-internal (no formal hook API) |
| Cache backends | `morphism.core.cache`, `morphism.core.pipeline` | `lookup/store/delete/close` behavior and key semantics | mismatch warm path before synthesis | stale transform reuse, regeneration storms, incorrect bridge reuse | soft-internal (drop-in class replacement) |
| Observability plugins | `morphism.utils.logger`, CLI/TUI integration | logger naming and event taxonomy | process startup and UI shell init | lost auditability, poor incident triage, hidden correctness regressions | soft-internal (handler-based integration) |

## Supported Extension Points

This section defines required methods, types, lifecycle callbacks, error semantics, and compatibility guarantees for each extension surface.

### Schema Adapters

Use this surface to add new schema domains and detection/inference routing for native command output.

#### Interface Contract Table: Schema Adapters

| Contract Area | Required Definition | Allowed Inputs/Outputs | Lifecycle Callback | Error Semantics | Compatibility Guarantee |
|---|---|---|---|---|---|
| Schema declaration | `Schema(name: str, data_type: Type, constraints: str)` | immutable value object | module import time | declaration errors are developer-time failures | stable dataclass semantics (`frozen`, value equality) |
| Constraint grammar | numeric bounds `a <= x <= b` or non-numeric constraints handled as runtime checks | verifier consumes numeric subset; non-numeric defers to runtime postcondition path | verifier call site | malformed numeric constraints can raise parser errors | grammar is stable for current numeric parser |
| Inference routing | extend `infer_schema(data: str) -> Schema` with deterministic precedence | raw stdout string -> known schema | native node execute completion | parsing failures must degrade to safer fallback, not crash | inference function contract is stable |
| Pending resolution | respect `Pending` as deferred type resolution boundary | `Pending -> concrete` after execution | runtime edge resolution in pipeline | unresolved mismatches must become explicit mismatch/bridge events | pipeline deferred-resolution behavior is stable |

Non-negotiable rules:

- Keep schema names globally stable once released; cache keying and operational telemetry depend on names.
- If introducing numeric constraints, ensure parser compatibility or add parser support and tests in the same change.
- Inference must be deterministic for identical input bytes.

### Transformation Providers

Use this surface to add model-backed, rules-backed, or hybrid transform generation.

#### Interface Contract Table: Transformation Providers

| Contract Area | Required Definition | Allowed Inputs/Outputs | Lifecycle Callback | Error Semantics | Compatibility Guarantee |
|---|---|---|---|---|---|
| Provider interface | subclass `LLMSynthesizer` and implement `async generate_functor(source: Schema, target: Schema) -> str` | two schemas in, single lambda string out | each mismatch attempt | backend/network issues must surface as typed synthesis failure | abstract method is stable |
| Candidate format | output must be a Python lambda expression accepted by sanitization/compile gate | expression string only | post-response sanitization | non-lambda responses are rejected and retried | lambda-only expectation is stable |
| Deterministic test path | provide deterministic behavior for CI path (similar to mock synthesizer strategy) | fixed mappings for known pairs | test runtime | deterministic provider should not depend on external services | test expectation stable |
| Retry behavior | provider may internally retry transient transport failures | bounded retries | request execution | exhaustion raises synthesis timeout/failure class | bounded-retry expectation stable |

Operational warning:

- Provider success does not imply acceptance. The pipeline enforces compile + verification + guardrail checks before bridge insertion.

### Verification Policy Hooks

Use this surface when adjusting acceptance policy or adding stronger safety checks.

Current state:

- No first-class plugin registry exists for policy hooks.
- Policy extensions are implemented by modifying or wrapping verifier functions and call sites.

#### Interface Contract Table: Verification Policy Hooks

| Contract Area | Required Definition | Allowed Inputs/Outputs | Lifecycle Callback | Error Semantics | Compatibility Guarantee |
|---|---|---|---|---|---|
| Verification entrypoint | preserve `verify_functor_mapping(source_schema, target_schema, transformation_logic, code_str=None, cfg=None) -> bool` | schema pair + callable -> `True`/`False` | every compiled candidate | `False` means reject-and-continue; typed failures can be retried; unknown terminal errors abort attempt series | function signature and boolean semantics are stable |
| Numeric proof pipeline | maintain SMT check of negated postcondition where constraints are numeric | symbolic variable + constraints + transform expression | after dry-run guard | solver `unknown` should remain typed verification failure | current solver behavior is stable |
| Non-numeric policy | preserve runtime postcondition path for non-symbolic domains | sample execution + type/range checks | when numeric parser does not apply | runtime evaluation errors reject candidate | runtime fallback contract is stable |
| Guardrail policies | optional domain-specific anchors (for critical pairs) | callable probes and tolerance checks | after generic verifier pass | guardrail failure must reject candidate, never silently downgrade | guardrail stage order is stable |

Correctness risk:

- Any policy change that increases acceptance without equivalent proof strength must be treated as a potential safety regression.

### Cache Backends

Use this surface to replace SQLite storage with another persistence layer while preserving correctness behavior.

#### Interface Contract Table: Cache Backends

| Contract Area | Required Definition | Allowed Inputs/Outputs | Lifecycle Callback | Error Semantics | Compatibility Guarantee |
|---|---|---|---|---|---|
| Lookup API | `lookup(source_name: str, target_name: str) -> str | None` | pair key -> lambda or miss | pre-synthesis warm path | backend failure should fail closed (miss) unless explicitly configured otherwise | method shape stable |
| Store API | `store(source_name: str, target_name: str, lambda_string: str) -> None` | verified candidate persist | on candidate acceptance | persistence errors should not corrupt in-memory execution path | method shape stable |
| Delete API | `delete(source_name: str, target_name: str) -> None` | eviction of stale candidate | verify/compile failure on cache hit | deletion failure must be logged and surfaced for ops triage | method shape stable |
| Resource API | `close() -> None` + context manager support | clean shutdown | app teardown | close failures should not hide earlier runtime failures | context-manager behavior stable |
| Key compatibility | key must remain deterministic on schema pair identity | source/target names | all cache operations | mismatched key strategy causes silent cache partitioning | schema-pair key invariant required |

Hard rule:

- Cached entries are never trusted without compile + verification re-check on read.

### Observability Plugins

Use this surface to route logs, metrics, and operational traces to enterprise systems.

#### Interface Contract Table: Observability Plugins

| Contract Area | Required Definition | Allowed Inputs/Outputs | Lifecycle Callback | Error Semantics | Compatibility Guarantee |
|---|---|---|---|---|---|
| Logger bootstrap | call `setup_logging(level)` once at startup; attach additional handlers under `morphism.*` namespace | log records in, external sink writes out | process start | sink failures must not crash pipeline execution | logger namespace is stable |
| Event semantics | preserve key event classes: mismatch, synthesis attempt, verification pass/fail, cache hit/store/delete, node execution failure | structured message or transformed record | throughout run | formatting errors should degrade gracefully | event family is stable conceptually |
| Correlation strategy | inject request/pipeline identifiers via formatter/filter/handler context | string IDs | per execution session | missing IDs reduce traceability but should not block execution | correlation fields are extension-defined |
| Redaction policy | strip secrets and sensitive payloads before sink write | message/fields -> sanitized fields | pre-write | redaction failure should fail closed when policy requires | no built-in redaction guarantee; plugin responsibility |

Audit requirement:

- Extensions must keep enough telemetry to reconstruct why a candidate was accepted or rejected.

## Contracts and Invariants

### Invariant Checklist

Contributors must preserve all of the following:

- Schema equality remains value-based and immutable.
- Edge compatibility is mandatory unless a verified bridge is inserted.
- Candidate acceptance order remains compile -> verifier -> guardrail.
- Cache hit path always recompiles and re-verifies before execution.
- Verification rejection never degrades into implicit acceptance.
- Non-zero native command exit remains a hard runtime error.
- Deferred `Pending` schemas resolve before downstream execution proceeds.
- All extension failures surface typed or logged failure causes.
- Timeouts and retries remain bounded and configurable.
- Observability changes never remove failure-class visibility.

Trust boundary invariants:

- Provider output is untrusted text until compile + verification complete.
- Native command output is untrusted input until inference and policy checks complete.
- Cache content is untrusted persistence until revalidated on read.

Security constraints:

- Do not widen eval globals without security review.
- Treat external model responses, subprocess output, and cache payloads as hostile.
- Enforce policy checks before bridge insertion, not after.
- Ensure logs do not leak credentials, tokens, or sensitive payload bodies.

## Implementation Workflow

### 1. Scaffolding

- Define extension objective and affected trust boundary.
- Add extension module under active tree (`src/morphism/...`) with explicit contract docstring.
- Wire extension at composition boundary (CLI app bootstrap or pipeline construction), not via hidden side effects.
- Add feature flag/env gate for new behavior; default to disabled unless risk is demonstrably low.

### 2. Local Development and Unit Testing

- Add unit tests for method-level contract behavior and failure semantics.
- Add deterministic fixtures for transform generation and verifier outcomes.
- Validate invariant checklist with explicit tests (not only happy paths).

### 3. Integration Validation

- Execute pipeline-level tests with mismatch scenarios, cache warm/cold paths, and runtime deferred schema resolution.
- Validate error propagation classes and operator-visible messages.
- Run with observability sink enabled and verify event completeness.

### 4. Release Safety Checks

- Backward-compat review against public signatures and behavior.
- Feature flag rollout plan with rollback switch.
- Failure-mode rehearsal: backend unavailable, verifier unknown, cache corruption, sink outage.
- Update maintainer docs and operational runbooks in the same PR.

## Testing and Validation

### Regression Test Requirements

Every extension PR must include, at minimum:

- Contract tests for each required interface method.
- Negative tests for malformed/untrusted input.
- Timeout/retry boundary tests.
- Cache stale-entry rejection tests (compile fail and verification fail paths).
- Compatibility tests proving existing built-in schemas and transformations still pass.
- End-to-end execution test covering one mismatch -> bridge -> cached replay cycle.
- Observability assertions for acceptance/rejection events.

Validation gates recommended before merge:

- full test suite pass (`pytest`).
- targeted extension test module pass in isolation.
- no new untyped exception leaks in execution path.
- deterministic CI mode for synthesis-related tests.

## Compatibility and Release Strategy

Backward compatibility policy:

- Keep stable signatures unchanged for `Schema`, `LLMSynthesizer.generate_functor`, `verify_functor_mapping`, and cache method set unless a versioned migration is published.
- If changing semantics (not signatures), document old/new behavior and migration impact.

Feature flags and migration-safe rollout:

- Stage 1: dark launch behind environment flag.
- Stage 2: opt-in for internal canary workloads.
- Stage 3: widen exposure with metric thresholds and automatic rollback trigger.
- Stage 4: make default only after regression-free soak window.

Enterprise hardening expectations:

- deterministic behavior in CI and pre-prod.
- bounded retries and bounded external call timeouts.
- audit-friendly logs with correlation IDs.
- explicit dependency and model endpoint pinning.
- documented disaster recovery for cache and provider outages.

## Troubleshooting

### End-to-end Extension Walkthrough

Example path: add a rules-backed transformation provider for stable numeric normalization and ship it safely.

1. Design and scope
- Goal: provider returns deterministic transforms for selected schema pairs and falls back to existing model provider.
- Risk: accidental broad acceptance of unsafe transforms.

2. Implementation
- Add `src/morphism/ai/rules_synthesizer.py` implementing `LLMSynthesizer`.
- Implement `generate_functor(source, target)`:
  - return `lambda x: x / 100.0` for `Int_0_to_100 -> Float_Normalized`.
  - delegate unsupported pairs to wrapped provider.
- Wire in CLI/bootstrap with env gate `MORPHISM_ENABLE_RULES_SYNTH=1`.

3. Contracts enforced
- Output remains lambda string only.
- Unsupported pairs still produce normal synthesis behavior.
- No bypass of compile/verify/guardrail pipeline.

4. Test plan
- Unit: known pair returns deterministic lambda.
- Unit: unsupported pair delegates exactly once.
- Integration: mismatch resolution inserts `AI_Bridge_Functor` and caches result.
- Regression: existing synthesis tests unchanged when flag disabled.

5. Release controls
- Merge behind disabled-by-default flag.
- Canary in one environment with strict telemetry monitoring.
- Roll back by unsetting feature flag if rejection rate or runtime failures spike.

6. Merge criteria
- All regression requirements pass.
- Invariant checklist signed in PR template.
- Operational runbook updated with enable/disable and rollback commands.

### Contribution Anti-patterns

- Accepting candidate transforms without verifier handoff.
- Adding schema constraints not parseable by current policy without fallback updates.
- Treating cache hit as trusted execution and skipping re-verification.
- Swallowing verifier or provider exceptions and continuing silently.
- Changing method signatures in stable surfaces without migration plan.
- Shipping extension behavior enabled by default with no canary path.
- Logging full untrusted payloads or secrets into persistent sinks.
- Using non-deterministic provider behavior in CI-critical tests.

Failure diagnosis quick map:

- Repeated compile rejects: provider output format drift.
- Repeated verifier rejects with same pair: bad candidate policy or unsupported expression form.
- Cache hit then immediate eviction loop: stale cache values or changed verification rules.
- Observability gaps during incidents: handler failures or missing correlation strategy.
