---
title: Transformations and Synthesis
description: Internal guide to mismatch-triggered transform generation, validation, and verified selection in Morphism Engine.
slug: /transformations-synthesis
---

## Synthesis Trigger and Inputs

Synthesis is invoked only when a pipeline edge is type-incompatible and a synthesizer client is configured.

Trigger predicate:

$$
Trigger(A,B) := (A \neq B) \land (llm\_client \neq \varnothing)
$$

Where:

- `A = node_a.output_schema`
- `B = node_b.input_schema`

Entry conditions and guardrails:

1. Mismatch class detection
- direct schema mismatch during append/add-branch (known schemas), or
- runtime mismatch after deferred `Pending` schema resolution.

2. Cache-first guardrail
- lookup by schema pair key before generation.
- cached code is recompiled and reverified before reuse.

3. Candidate admissibility gates
- syntactic compile gate (`eval` success)
- verifier gate (`verify_functor_mapping`)
- boundary-specific semantic guardrail for `Int_0_to_100 -> Float_Normalized` (anchor checks at 0, 50, 100)

Mismatch classes observed in implementation:

1. Structural schema mismatch: `JSON_Object -> Float_Normalized`.
2. Domain mismatch within numerics: `Int_0_to_100 -> Int_0_to_10`.
3. Deferred runtime mismatch: `Pending -> concrete` transitions that become incompatible after native inference.

### Synthesis Lifecycle Table

| Step | Input | Operation | Output | Reject/Continue Condition |
|---|---|---|---|---|
| 0 | `(A, B)` schema pair | cache lookup | cached code or miss | miss -> step 2 |
| 1 | cached code | compile + verify | accepted bridge or cache eviction | compile fail / verify fail -> evict + step 2 |
| 2 | `(A, B)` + config | prompt assembly + backend request | raw model text | transport failure retries inside synthesizer |
| 3 | raw text | sanitization/canonical extraction | lambda string candidate | extraction fail -> synthesis error path |
| 4 | candidate string | compile (`eval`) | callable | compile fail -> next attempt |
| 5 | callable + schemas | verifier check | boolean / exception | false/exception -> next attempt |
| 6 | callable + boundary rule | semantic anchor checks (if applicable) | pass/fail | fail -> next attempt |
| 7 | admissible candidate | cache store + node insertion | `AI_Bridge_Functor` | success terminates loop |
| 8 | attempt budget exhausted | raise error | `VerificationFailedError` | terminal for this boundary |

## Candidate Generation

Generation architecture is single-candidate-per-attempt, sequential.

Prompt/context assembly:

- Includes source schema name/type/constraints.
- Includes target schema name/type/constraints.
- Includes explicit instruction to return exactly one Python lambda.
- Injects JSON handling rule for JSON-derived string payloads.

Constraint injection model:

- Constraints are textual in prompt (`constraints=(...)`).
- Hard safety is enforced downstream by verifier; prompt constraints are advisory generation context.

Candidate enumeration strategy:

- No explicit beam or n-best list in current implementation.
- At each attempt, backend returns one candidate text.
- Resolver loops attempts up to `MORPHISM_MAX_SYNTHESIS_ATTEMPTS`.

Deterministic controls:

- `MORPHISM_MODEL_NAME`
- `MORPHISM_OLLAMA_URL`
- `MORPHISM_LLM_REQUEST_TIMEOUT`
- `MORPHISM_MAX_SYNTHESIS_ATTEMPTS`
- deterministic provider path for testing: `MockLLMSynthesizer`

Candidate representation and normalization:

1. Raw response text (`data["response"]`).
2. Sanitized candidate string (`_sanitise`):
- remove markdown fences
- normalize whitespace
- extract first lambda-like segment
- trim quotes/backticks/trailing punctuation
3. Compiled callable via `eval`.
4. Optional symbolic IR via verifier AST translation (`_symbolic_transform_from_code`).

### Transform Representation Overview

| Representation Layer | Type | Producer | Consumer | Purpose |
|---|---|---|---|---|
| Raw candidate text | `str` | synthesizer backend response | sanitizer | initial untrusted payload |
| Normalized lambda string | `str` | `_sanitise` | compile gate, cache, verifier | canonical candidate token for execution and persistence |
| Executable callable | `Callable[[Any], Any]` | `eval` | runtime bridge execution | actual transform application |
| Symbolic expression IR | Z3 expression tree | AST translator in verifier | solver | proof query encoding |
| Persisted artifact | SQLite row (`lambda_string`) | cache store | future lookup | warm-path reuse |

Canonicalization scope (current):

- lexical normalization only.
- no algebraic simplification or semantic canonical form derivation.

## Candidate Validation and Selection

Validation stack order:

1. Compile gate
2. Verifier gate
3. boundary-specific semantic guardrail (where defined)

Validity predicate:

$$
Valid(h, A, B) := Compile(h) \land Verify(h, A, B) \land Guards(h, A, B)
$$

Selection rule:

$$
Select := \text{first } h_i \text{ in attempt order such that } Valid(h_i, A, B)
$$

This is not global-optimal ranking; it is first-admissible selection.

Conflict resolution between multiple valid candidates:

- Current resolver does not compare multiple valid candidates jointly.
- First admissible candidate wins and is cached.
- Subsequent runs typically reuse cached transform unless re-verification fails.

### Candidate Ranking Criteria Table

Current implementation uses gate-priority acceptance, not numeric ranking scores.

| Criterion | Type | Enforced By | Priority | Effect |
|---|---|---|---|---|
| Lambda extraction success | hard gate | sanitizer | highest | reject non-lambda outputs |
| Compile success | hard gate | resolver compile step | high | reject syntactically invalid code |
| Verification safety | hard gate | Z3 verifier/runtime postcondition | high | reject unsafe or indeterminate candidates |
| Boundary semantic anchors | hard gate (specific pair) | pipeline guardrail | medium-high | reject semantically off normalization mappings |
| Generation order | tie-break | attempt loop order | low | first valid candidate selected |

Implication for contributors:

- If richer scoring is needed (cost/complexity/stability), add explicit scoring layer before acceptance and update cache policy accordingly.

## Verification Handoff

Handoff contract from synthesis resolver to verifier:

Inputs:

- `source_schema`
- `target_schema`
- compiled callable
- lambda code string

Expected outputs:

- `True`: admissible
- `False`: unsafe candidate (recoverable to next attempt)
- `VerificationFailedError` / `ValueError`: verifier error (recoverable to next attempt unless attempts exhausted)

Compositional correctness relation:

Given upstream `f: X -> A`, bridge `h: A -> B`, downstream `g: B -> Y`, admitted composition is:

$$
g \circ h \circ f
$$

only when `Valid(h, A, B)` holds.

Trust boundary:

- Synthesis output is untrusted until verifier acceptance.
- Cache does not bypass trust boundary because cached code is reverified on read.

## Caching and Reuse

Cache keying and policy:

- Key basis: schema pair (`source_name::target_name`) hashed in cache layer.
- Stored value: selected lambda string.
- On hit: compile + verify before use.

Cold vs warm behavior:

- Cold path: synthesize -> validate -> store.
- Warm path: lookup -> revalidate -> execute.

Replay behavior:

- Replay is deterministic only to the extent cache content and verifier semantics remain stable.
- Clearing `.morphism_cache.db` forces regeneration.

Invalidation behavior:

- Automatic: cached candidate compile failure or verify failure triggers eviction.
- Manual: operator removes cache DB.

Cached verification opportunities:

- Current runtime re-verifies each cache hit for safety.
- No explicit proof-result memo separate from code cache.

## Failure Handling

Common failure signatures and remediations:

1. `Ollama synthesis failed after ... retries`
- Cause: backend unavailable/timeout/response issues.
- Remediation: verify endpoint/model, adjust request timeout, use deterministic mock in CI.

2. `Rejecting functor (compile failed): ...`
- Cause: extracted lambda not valid Python expression.
- Remediation: tighten prompt constraints, improve sanitizer robustness, add retry diagnostics.

3. `Rejecting functor (verifier error): ...`
- Cause: unsupported expression in verifier translator or constraint parse issue.
- Remediation: extend verifier support set or constrain generated expression language.

4. `Functor F(A -> B) failed verification after N attempt(s)`
- Cause: no admissible candidate found within budget.
- Remediation: pin explicit transform, increase attempt budget cautiously, simplify boundary.

5. `Rejecting functor (anchors failed): ...`
- Cause: candidate passes generic constraints but fails canonical normalization semantics.
- Remediation: keep anchor guardrail for this pair; tune synthesis prompt with stronger examples.

Recoverable vs terminal states:

- Recoverable: candidate-level compile/verify/anchor failures while attempts remain.
- Terminal: attempt budget exhausted for boundary, synthesis transport exhausted, or no LLM path available.

## Worked Example

Scenario: boundary mismatch in chain

```text
emit_raw | render_float
```

Raw mismatch:

- `emit_raw` output schema: `Int_0_to_100`
- `render_float` input schema: `Float_Normalized`

Internal artifacts (representative):

1. Mismatch record

```text
src=Int_0_to_100, tgt=Float_Normalized
```

2. Cache lookup

```text
lookup("Int_0_to_100", "Float_Normalized") -> miss
```

3. Prompt payload (abbreviated)

```text
Input Schema: name=Int_0_to_100, constraints=(0 <= x <= 100)
Output Schema: name=Float_Normalized, constraints=(0.0 <= x <= 1.0)
Return only Python lambda string
```

4. Candidate after sanitization

```text
lambda x: x / 100.0
```

5. Validation path

- compile: pass
- verifier: pass (`UNSAT` for negated postcondition)
- anchor checks: `f(0)=0.0`, `f(50)=0.5`, `f(100)=1.0` pass

6. Selection and persistence

```text
selected = lambda x: x / 100.0
cache.store("Int_0_to_100", "Float_Normalized", "lambda x: x / 100.0")
```

7. Inserted bridge node

```text
AI_Bridge_Functor: Int_0_to_100 -> Float_Normalized
```

8. Final executable chain

```text
emit_raw -> AI_Bridge_Functor -> render_float
```

Expected emission:

```text
>>> [RENDERED UI]: 0.5
```
