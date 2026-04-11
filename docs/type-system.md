---
title: Morphism Engine Type System
description: Formal-practical reference for Morphism Engine type modeling, compatibility rules, mismatch semantics, and transformation safety.
slug: /type-system
---

## Type Model Overview

Morphism 3.1.x uses schema objects as runtime type contracts.

Core type entity:

- `Schema(name, data_type, constraints)`
- Equality is structural by dataclass value equality.

Built-in schemas in core:

- `Int_0_to_100`: `int`, constraint `0 <= x <= 100`
- `Float_Normalized`: `float`, constraint `0.0 <= x <= 1.0`
- `String_NonEmpty`: `str`, constraint `len(x) > 0`
- `Int_0_to_10`: `int`, constraint `0 <= x <= 10`
- `JSON_Object`: `str`, constraint `len(x) > 0`
- `CSV_Data`: `str`, constraint `len(x) > 0`
- `Plaintext`: `str`, empty constraint
- `Pending`: `str`, empty constraint (placeholder before inference)

Conceptual model:

- Type identity is not only Python primitive (`int`, `float`, `str`) but also semantic domain (`name`, `constraints`).
- Two schemas with same primitive type can still be incompatible if names/constraints differ.

Primitive vs composite structures:

- Primitive value carriers: `int`, `float`, `str`.
- Composite payloads (JSON/CSV) are currently modeled as `str` with semantic schema labels; they are not native nested typed ASTs inside core.

Optional/nullable behavior:

- No first-class nullable/optional schema in current core schema set.
- `None` appears as pipeline initial input sentinel for source stages, not as a typed nullable domain.
- Nullable semantics must be modeled explicitly via guard stages or custom schemas.

Schema normalization assumptions:

- Native command output is normalized to one of `JSON_Object`, `CSV_Data`, `Plaintext` via inference heuristics.
- For synthesis from JSON-like schemas, transforms are expected to parse string payloads explicitly.

Compatibility and coercion policy (high level):

- Direct edge compatibility requires schema equality.
- If unequal and LLM path is available, engine attempts synthesis + verification of a bridge.
- Coercion is never silent: it is either explicit (pinned transform) or admitted through verified bridge insertion.

### Type Rule Summary Table

| Rule ID | Rule | Formal Form | Engine Behavior |
|---|---|---|---|
| TR-1 | Direct compatibility | `A \equiv B` | Edge accepted without bridge |
| TR-2 | Mismatch requires repair | `A \not\equiv B` | Trigger `_resolve_mismatch` if LLM configured |
| TR-3 | No-repair mismatch is fatal | `A \not\equiv B \land \neg repair_enabled` | Raise `SchemaMismatchError` |
| TR-4 | Bridge admission requires safety | `verify(h: A \to B) = true` | Insert `AI_Bridge_Functor` |
| TR-5 | Unsafe bridge rejected | `verify(h) = false` | Retry candidate or fail with `VerificationFailedError` |
| TR-6 | Deferred typing | `B = Pending` | Edge accepted provisionally; checked at runtime |
| TR-7 | Cache trust is conditional | `cache_hit(h)` | Recompile + reverify before use |

Notation:

- `A`, `B`: schemas
- `h`: candidate bridge transform
- `\equiv`: schema equality

## Inference and Normalization

Inference happens only for native subprocess stages.

Inference order in core:

1. parse as JSON object/array -> `JSON_Object`
2. detect CSV dialect on multiline text with allowed delimiter -> `CSV_Data`
3. fallback -> `Plaintext`

Type information flow:

1. Parsing/planning stage constructs nodes.
- known registry nodes carry concrete schema in/out.
- unknown/native nodes start with `Pending`.

2. Runtime execution of native node.
- stdout captured as text.
- `infer_schema(stdout)` resolves `output_schema`.

3. Runtime boundary check.
- downstream `Pending` input may be concretized.
- if concretized output/input mismatch remains, synthesis-verification path runs.

Ambiguity boundaries:

- JSON parse failure does not raise typing error; it falls through to CSV/plaintext heuristics.
- Ambiguous text defaults to `Plaintext`, which is intentionally permissive but can increase mismatch frequency downstream.

Determinism notes:

- Inference is deterministic for a fixed byte payload and Python runtime behavior.
- End-to-end type path may still vary if upstream native command output format changes.

Strict mode note:

- Native core 3.1.x has no built-in strict mode switch.
- Strict behavior is typically provided via wrappers/policies: fail on fallback-to-Plaintext or on unpinned critical boundaries.

## Compatibility and Conversion Rules

### Compatibility predicate

Define compatibility predicate:

$$
Compat(A,B) := (A = B)
$$

Core compatibility is exact equality, not subtype/constraint implication.

### Conversion admissibility

For mismatch `A -> B`, a conversion is admissible iff candidate bridge `h` passes verification:

$$
Admissible(h, A, B) := Verify(h, A, B) = \text{true}
$$

For numeric constraints, verifier checks counterexample satisfiability over source range and target postcondition.

### Compatibility Matrix

Legend:

- `Direct`: no bridge required
- `Bridge`: bridge may be synthesized/required
- `Deferred`: provisional until runtime inference
- `Fail`: immediate error if no synthesis path

| Producer \ Consumer | Int_0_to_100 | Float_Normalized | String_NonEmpty | Int_0_to_10 | JSON_Object | CSV_Data | Plaintext | Pending |
|---|---|---|---|---|---|---|---|---|
| Int_0_to_100 | Direct | Bridge | Bridge | Bridge | Bridge | Bridge | Bridge | Deferred |
| Float_Normalized | Bridge | Direct | Bridge | Bridge | Bridge | Bridge | Bridge | Deferred |
| String_NonEmpty | Bridge | Bridge | Direct | Bridge | Bridge | Bridge | Bridge | Deferred |
| Int_0_to_10 | Bridge | Bridge | Bridge | Direct | Bridge | Bridge | Bridge | Deferred |
| JSON_Object | Bridge | Bridge | Bridge | Bridge | Direct | Bridge | Bridge | Deferred |
| CSV_Data | Bridge | Bridge | Bridge | Bridge | Bridge | Direct | Bridge | Deferred |
| Plaintext | Bridge | Bridge | Bridge | Bridge | Bridge | Bridge | Direct | Deferred |
| Pending | Deferred | Deferred | Deferred | Deferred | Deferred | Deferred | Deferred | Deferred |

Important practical caveat:

- `Bridge` means “possible via synthesis + verification”, not guaranteed.

### Coercion policy

- Implicit coercion is disallowed.
- Explicit coercion path is either:
  1. user-pinned transform node, or
  2. synthesized bridge admitted by verifier.

Lossy conversion risk categories:

1. Structural loss: dropping keys/columns from composite payload.
2. Semantic loss: numeric range compression (for example 0-100 to 0-1).
3. Precision loss: float/int truncation/rounding.

Core behavior does not automatically classify lossiness level for users; this is inferred from transform semantics and verifier outcome.

## Mismatch Detection and Error Semantics

Detection locations:

1. Append-time (`append`/`add_branch`) for concrete schemas.
2. Execute-time for deferred schemas (`Pending` resolved at runtime).

Mismatch classes:

1. Structural mismatch
- Different schema families (for example `JSON_Object` to `Float_Normalized`).
- Typical remediation: parse/extract/normalize bridge.

2. Semantic mismatch
- Same primitive carrier but different domain constraints (for example `Int_0_to_100` to `Int_0_to_10`).
- Typical remediation: clamp/rebucket explicit transform, then verify.

3. Lossy-risk mismatch
- Conversion may satisfy target constraint but lose information.
- Typical remediation: split pipeline into audit branch + transformed branch.

### Strict vs permissive behavior comparison

| Behavior Aspect | Core Default (3.1.x) | Strict Wrapper/Policy Mode (recommended) |
|---|---|---|
| Fallback on ambiguous inference | allow (`Plaintext`) | fail or quarantine payload |
| Unpinned critical boundary | allow synthesis path | deny unless pinned transform |
| Solver `unknown` | verification failure | verification failure (same), plus immediate alerting |
| Cache use | allowed with reverify | allowed only for policy-allowed schema pairs |
| Generated code execution | allowed post-verify | optionally disallowed for regulated boundaries |

### 3+ mismatch case studies with remediation

Case 1: Numeric normalization mismatch

- Boundary: `Int_0_to_100 -> Float_Normalized`
- Symptom: direct edge mismatch
- Remediation: bridge `x / 100.0`
- Outcome: verification pass, bridge inserted

Case 2: Strict bounded target fails

- Boundary: `Int_0_to_100 -> Int_0_to_10`
- Symptom: verifier rejects unsafe candidate(s)
- Remediation: pinned clamp transform `max(0, min(10, int(x/10)))`
- Outcome: deterministic pass under explicit transform

Case 3: Ambiguous plaintext payload

- Boundary: `Plaintext -> Float_Normalized` with payload `score=abc`
- Symptom: parse failures cause candidate rejection
- Remediation: add guard stage to emit safe numeric default or dead-letter
- Outcome: stabilized boundary typing and predictable behavior

Case 4: JSON field drift

- Boundary: producer changed `score` path (`metrics.score`)
- Symptom: prior bridge fails at runtime or verifier stage
- Remediation: schema-version pinning (`API_V1_Score`, `API_V2_Metrics`) + pinned bridges
- Outcome: controlled migration and explicit compatibility break handling

Error semantics by type class:

- `SchemaMismatchError`: mismatch without viable repair path.
- `VerificationFailedError`: candidate transforms rejected/exhausted.
- `EngineExecutionError`: runtime execution failure (native command or bridge runtime fault).

## Verification Link

Verification is the admission control between inferred/synthesized typing and executable composition.

For supported numeric domains, verifier checks:

$$
\forall x \in Dom(A),\; h(x) \in Dom(B)
$$

via negated satisfiability query:

$$
\exists x \in Dom(A)\; \land\; h(x) \notin Dom(B)
$$

Result interpretation:

- `UNSAT` -> safe transform for modeled constraints.
- `SAT` -> unsafe, reject transform.
- `unknown` -> fail closed (`VerificationFailedError`).

Runtime guardrails beyond SMT:

- pre-solver dry-run detects obvious type-shape errors.
- additional anchor checks exist for canonical normalization boundary (`Int_0_to_100 -> Float_Normalized`).

Safety guarantee scope:

- Guarantees apply to modeled constraints and supported transform expression subset.
- They do not imply full semantic equivalence or side-effect freedom.

## Operational Best Practices

Practical policy recommendations:

1. Schema pinning
- Pin critical boundaries with explicit custom schemas and explicit transform nodes.
- Avoid relying on inferred/plaintext boundaries in regulated flows.

2. Explicit contract boundaries
- Introduce guard/validation stages before expensive or strict consumers.
- Normalize upstream formats to deterministic JSON whenever possible.

3. Production-safe defaults
- Set bounded solver and synthesis timeouts.
- Reduce synthesis attempts in CI for deterministic failure.
- Keep cache reuse intentional; clear cache on schema/version policy changes.

### Production type-safety checklist

1. Are critical boundaries pinned with explicit schema names and transforms?
2. Are native outputs normalized to stable structured formats?
3. Are ambiguous `Plaintext` paths either guarded or disallowed?
4. Is verification mandatory for generated bridges in this environment?
5. Are solver and request timeouts bounded for SLA and fail-fast behavior?
6. Are schema-version migrations explicit (v1/v2 schemas) rather than implicit key drift?
7. Are lossy conversions audited (dual-branch or logging of pre/post values)?
8. Is cache invalidation strategy documented for model/constraint changes?
9. Are failure classes mapped to operational runbook actions?
10. Are regression tests covering previously failing boundaries?
