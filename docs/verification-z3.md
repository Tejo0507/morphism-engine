---
title: Verification (Z3)
description: Implementation-oriented specification of Morphism Engine transform verification using SMT checks and runtime guards.
slug: /verification-z3
---

## Verification Scope and Guarantees

Verification in Morphism is an admission gate for synthesized (or cached) boundary transforms before they are inserted into execution graphs.

What is proven:

1. For supported numeric constraint domains, candidate transform `h` maps source-domain values into target-domain constraints.
2. For supported string constraint domains, candidate transform `h` is checked with Z3 string theory (`z3str3`) against regex/length/contains-style constraints.
2. Candidate is rejected if solver finds a counterexample.
3. Candidate is rejected if solver cannot decide (`unknown`) under current timeout policy.

Formal target property:

$$
\forall x \in Dom(S_{src}),\; h(x) \in Dom(S_{tgt})
$$

Solver query form (negated postcondition):

$$
\exists x \in Dom(S_{src})\; \wedge \; h(x) \notin Dom(S_{tgt})
$$

Interpretation:

- `UNSAT`: property proven for modeled constraints.
- `SAT`: counterexample exists, property violated.
- `UNKNOWN`: no proof verdict within solver capabilities/time budget.

Intentionally out of scope:

1. Full semantic equivalence to user intent (the verifier checks constraint preservation, not intent alignment).
2. Side-effect freedom or non-interference guarantees.
3. Arbitrary Python language completeness in symbolic encoding.
4. End-to-end multi-stage semantic proofs across entire pipelines.

Boundary between syntactic checks and semantic proofs:

- Syntactic checks:
  - lambda extraction/sanitization
  - Python parse validity
  - supported AST subset for symbolic translation
- Semantic proof checks:
  - satisfiability of negated postcondition over source domain
  - runtime postcondition checks for non-symbolically modeled domains
  - proof certificate artifact emission for every verification attempt

## Encoding Pipeline

Verification path is implemented as a staged encoder and checker.

1. Pre-solver dry-run guard
- Execute compiled lambda on schema-specific dummy value.
- Reject obvious type-shape errors (`TypeError`, `KeyError`, `NameError`, `AttributeError`, `ValueError`).

2. Domain classification
- If source constraint is numeric interval (`lo <= x <= hi`), continue to symbolic SMT path.
- Else if source/target are string schemas and candidate AST is supported, continue to symbolic string SMT path (`z3str3`).
- Otherwise, fallback to runtime postcondition check path.

3. Constraint normalization
- Parse source/target constraint strings to internal condition terms.
- For numeric intervals:
  - source over integer symbol `x`
  - target over real symbol `y`
- For supported string constraints:
  - source over string symbol `x`
  - target over string symbol `y`
  - supported clauses include `len(x)`, `contains(x, ...)`, `not contains(...)`, `regex(x, ...)`

4. Transformation encoding
- Preferred path: AST translation from `code_str` into Z3 expression.
- Legacy fallback path exists only when code string unavailable.

5. Proof query assembly
- assert source precondition
- assert `y = h(x)`
- assert negated target postcondition

6. Solver decision and admission
- `UNSAT` -> accept candidate
- `SAT` -> reject candidate
- `UNKNOWN` -> raise verification error
- write proof certificate transcript (mode, assertions, SAT result, model if any)

### Constraint Mapping Table (pipeline concept -> SMT encoding)

| Pipeline Concept | Internal Representation | SMT Encoding |
|---|---|---|
| Source schema domain | `Schema.constraints` string | `And(lo <= x, x <= hi)` over `Int("x")` |
| Candidate transform | lambda code string | AST-translated expression `y_expr` over `x` |
| Transform output variable | intermediate symbolic target | `Real("y")` with assertion `y == y_expr` |
| Target schema requirement | `Schema.constraints` string | `target_cond(y)` |
| Safety obligation | must hold for all source values | encoded as `Not(target_cond(y))` with source constraints |
| Proof query | counterexample search | `solver.check()` on assembled constraints |

### Preconditions, invariants, postconditions in implementation terms

Preconditions:

1. Candidate callable is compilable.
2. Candidate passes dry-run type guard for source schema dummy.
3. Source/target constraints parsable for symbolic path (numeric interval form).

Invariants:

1. Solver timeout is always applied from config.
2. Counterexample model is logged on SAT outcomes.
3. Cached candidate is never trusted without recompilation and re-verification.

Postconditions:

1. Accepted candidate is safe under modeled constraints (`UNSAT` path).
2. Rejected candidate does not enter execution graph.
3. Unknown verdict is treated as failure, not soft success.

## Solver Lifecycle

### Verification Lifecycle Sequence

1. Pipeline mismatch detected (`S_src != S_tgt`).
2. Cache lookup by schema pair.
3. Candidate obtained (cache hit or synthesis).
4. Candidate compiled to callable.
5. Verifier called with `(source_schema, target_schema, callable, code_str)`.
6. Dry-run guard executes candidate on dummy value.
7. Numeric-domain branch:
- build solver
- set timeout
- encode source constraints
- encode transform relation
- encode negated target condition
- check SAT status
8. Non-numeric branch:
- runtime postcondition check path
9. Verdict returned to pipeline:
- pass -> insert bridge node
- fail -> retry next candidate or terminate after attempt budget

### Query lifecycle and timeout strategy

- One solver instance per verification call.
- Timeout set using `MORPHISM_Z3_TIMEOUT_MS`.
- No incremental push/pop session reuse in current implementation.
- Unknown/timeout is treated as verification error (fail closed).

### SAT/UNSAT/UNKNOWN decision matrix

| Solver Result | Meaning | Candidate Status | Pipeline Action | User-Visible Effect |
|---|---|---|---|---|
| `UNSAT` | no violating input exists under model | accepted | bridge inserted, may be cached | pipeline continues |
| `SAT` | violating input exists | rejected | try next candidate or fail when exhausted | verification failure after retries |
| `UNKNOWN` | solver cannot decide in limits | rejected with error | fail current candidate immediately; may retry next | explicit verification error/timeout semantics |

## Result Semantics

Admission decision output semantics:

- `True` from verifier means candidate is admissible under current model.
- `False` means candidate is unsafe (counterexample found or runtime guard failed).
- `VerificationFailedError` means indeterminate/unsupported verification state that is treated as failure.

Recoverable vs terminal states:

Recoverable (within same mismatch resolution cycle):

1. Candidate compile failure.
2. Candidate SAT rejection.
3. Candidate verifier `ValueError` for unsupported expression.

Terminal for current pipeline run (after retry budget exhausted):

1. repeated unsafe candidates leading to `VerificationFailedError` at orchestrator level.
2. synthesis source exhaustion/timeouts with no acceptable candidate.

Diagnostic artifacts emitted:

- Structured log lines for proof pass/fail and counterexample model on SAT.
- Pipeline-level rejection logs (compile failure, verifier error, anchors failure).
- Dedicated proof certificate JSON file written to `MORPHISM_PROOF_CERT_DIR` (default `logs/proofs`).

## Performance Characteristics

### Solver cost drivers

1. Constraint complexity (numeric range and expression structure).
2. AST transform complexity (nested min/max/casts/arithmetic depth).
3. Timeout settings (`MORPHISM_Z3_TIMEOUT_MS`).
4. Candidate retry count per mismatch.

### Constraint size growth

- Grows with expression tree size of candidate transform.
- Grows with number of mismatch edges requiring independent verification.
- Branching pipelines can amplify total verification calls when many edges mismatch.

### Incremental and cached verification opportunities

Current implementation:

- Cache stores transform code by schema pair.
- Cached code is re-verified on each reuse.
- No solver state reuse between calls.

Optimization opportunities for contributors:

1. Optional proof-result memoization keyed by `(schema pair, code hash, verifier version)`.
2. Incremental solver sessions for repeated structurally similar checks.
3. Constraint canonicalization and common-subexpression reuse.

## Failure Analysis and Debugging

### Failure case study 1: unsupported lambda AST

Symptom:

- verifier raises error such as unsupported function/operator.

Root cause:

- candidate contains AST node outside supported translator subset.

Remediation:

1. constrain synthesis prompt to supported operations.
2. extend translator for new operation with explicit tests.
3. keep fallback policy fail-closed until extension validated.

### Failure case study 2: solver unknown due to timeout

Symptom:

- verification error indicates unknown/possible timeout.

Root cause:

- query too complex for configured timeout.

Remediation:

1. increase `MORPHISM_Z3_TIMEOUT_MS` within operational bounds.
2. simplify candidate expression shape.
3. reduce mismatch complexity via pinned explicit transforms.

### Failure case study 3: non-numeric domain false confidence risk

Symptom:

- symbolic path skipped; runtime postcondition path used.

Root cause:

- source constraint not numeric interval encodable.

Remediation:

1. model critical domains with explicit numeric constraints where possible.
2. add stronger runtime guards and schema pinning.
3. mark such boundaries as high-scrutiny in policy.

Debugging entry points:

1. verification function entry and dry-run path.
2. AST translation branch.
3. solver result branch logging.
4. pipeline mismatch resolver retry loop.

Recommended debug sequence:

1. Enable DEBUG logging.
2. Capture source/target schema names and candidate code.
3. Re-run verifier in isolation with same code and config.
4. Inspect SAT model (if present) to construct minimal counterexample test.
5. Add regression test before changing translator/constraint parser behavior.

## Extension Guidelines

### Contributor checklist for adding new verifiable transformation classes

1. Define exact transform class scope and expected input/output schemas.
2. Ensure transform can be represented in supported IR (or extend IR translator first).
3. Add/extend constraint parser support if new constraint forms are required.
4. Preserve fail-closed behavior for unknown/unsupported constructs.
5. Add tests for:
- proof pass case
- proof fail (counterexample) case
- unknown/timeout case
- dry-run rejection case
6. Validate integration through mismatch resolver path (compile, verify, cache, execute).
7. Document trusted assumptions and any residual unsoundness boundaries.

### Soundness and risk model

Assumptions required for validity:

1. Constraint strings correctly encode intended domain semantics.
2. AST translation is semantics-preserving for supported constructs.
3. Candidate code evaluated is the same code encoded symbolically.

Trusted Computing Base (TCB):

- Python runtime and parser
- AST translator implementation
- Z3 solver correctness
- orchestrator glue code around verification decisions

Primary unsoundness entry points:

1. mismatch between executable semantics and symbolic translator semantics.
2. unsupported constructs silently bypassing symbolic checks (must not happen in strict path).
3. non-numeric fallback path used for boundaries that require stronger proof guarantees.

Compatibility boundaries for contributors:

- Maintain verifier result semantics (`True`/`False`/exception) to avoid breaking orchestrator logic.
- Maintain fail-closed treatment of `unknown` unless explicitly redesigning safety policy.
- Version and migration-note any change to constraint grammar or AST support set.
