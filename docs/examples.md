---
title: Morphism Engine Examples
Description: Practical examples catalog for failure-to-success pipeline integration with synthesis, verification, and cache-aware operation.
slug: /examples
---

## Examples Index Table

| ID | Domain | Scenario | Complexity | Data Format | Verification Cost | Runtime Profile | Tags |
|---|---|---|---|---|---|---|---|
| EX-01 | API/JSON | score normalization from JSON API payload | Low | JSON | Medium | Cold miss then warm | local, cache |
| EX-02 | API/JSON | nested JSON extraction to normalized float | Low | JSON | Medium | Cold miss then warm | local |
| EX-03 | logs/metrics | log line to bounded metric pipeline | Low | Plaintext | Medium | Warm-optimized | cache |
| EX-04 | CSV/TSV | CSV first-column ingestion to float consumer | Medium | CSV | Medium | Cold miss | local |
| EX-05 | infra/devops | command output health ratio to UI renderer | Medium | Plaintext | Medium | Warm-optimized | cache |
| EX-06 | API/JSON | strict schema v1 pinned transform | Medium | JSON | Low | Deterministic | schema-pin |
| EX-07 | API/JSON | strict schema v2 pinned transform | Medium | JSON | Low | Deterministic | schema-pin |
| EX-08 | logs/events | event severity routing with guard stage | Medium | Plaintext | Medium | Mixed | local |
| EX-09 | CLI-to-DB | JSON row to SQL insert statement stage | Medium | JSON | Medium | Cold miss | local |
| EX-10 | compliance/audit | audit payload hash and score normalization | Medium | JSON | Medium | Warm-optimized | cache |
| EX-11 | infra/devops | branch fan-out readiness checks | Medium | Plaintext | Medium | Parallel branch | local |
| EX-12 | API/JSON | intentional verification fail and correction | High | JSON | High | Fails then pass | fail-case |
| EX-13 | metrics | strict bounded target verification fail fix | High | Numeric | High | Fails then pass | fail-case |
| EX-14 | compliance/audit | enterprise-safe policy envelope pipeline | High | JSON | High | Controlled | enterprise |
| EX-15 | CI automation | non-interactive deterministic batch smoke | High | Mixed | Low | CI optimized | ci |

Notes:

- Verification cost is relative to number/complexity of mismatched boundaries.
- Runtime profile assumes local SQLite cache file at .morphism_cache.db.

## Beginner Track (quick wins)

### EX-01 API score normalization from JSON payload

1) Problem statement

A producer emits JSON text while consumer expects Float_Normalized.

2) Raw source command(s)

~~~bash
morphism
~~~

~~~text
µ> echo '{"score": 85}'
~~~

3) Target consumer command(s)

~~~text
µ> render_float
~~~

4) Mismatch diagnosis

Inferred source schema is JSON_Object, consumer expects Float_Normalized.

5) Synthesized transformation sketch

~~~text
lambda x: float(__import__('json').loads(x)['score']) / 100.0
~~~

6) Verification result

~~~text
Z3 verification passed for JSON_Object -> Float_Normalized boundary
~~~

7) Final working command sequence

~~~text
µ> echo '{"score": 85}' | render_float
~~~

8) Expected output snippet

~~~text
>>> [RENDERED UI]: 0.85
~~~

9) Production hardening notes

- Validate presence and bounds of score in upstream API adapter.
- Keep payload JSON-only; avoid mixed log noise.

### EX-02 Nested JSON extraction

1) Problem statement

Payload is nested and consumer requires normalized float.

2) Raw source command(s)

~~~text
µ> echo '{"metrics":{"cpu":42}}'
~~~

3) Target consumer command(s)

~~~text
µ> render_float
~~~

4) Mismatch diagnosis

JSON_Object to Float_Normalized mismatch.

5) Synthesized transformation sketch

~~~text
lambda x: float(__import__('json').loads(x)['metrics']['cpu']) / 100.0
~~~

6) Verification result

~~~text
Z3_PROOF_PASS True
~~~

7) Final working command sequence

~~~text
µ> echo '{"metrics":{"cpu":42}}' | render_float
~~~

8) Expected output snippet

~~~text
>>> [RENDERED UI]: 0.42
~~~

9) Production hardening notes

- Guard against missing keys with a pre-validation stage.
- Emit canonical JSON schema from producer service.

### EX-03 Log line to metric renderer

1) Problem statement

Log emitter prints plaintext score line.

2) Raw source command(s)

~~~text
µ> echo 'score=77'
~~~

3) Target consumer command(s)

~~~text
µ> render_float
~~~

4) Mismatch diagnosis

Plaintext to Float_Normalized mismatch.

5) Synthesized transformation sketch

~~~text
lambda x: float(x.split('=')[1]) / 100.0
~~~

6) Verification result

~~~text
Boundary verified; no counterexample found in target range
~~~

7) Final working command sequence

~~~text
µ> echo 'score=77' | render_float
~~~

8) Expected output snippet

~~~text
>>> [RENDERED UI]: 0.77
~~~

9) Production hardening notes

- Pre-filter malformed log lines.
- Keep delimiter stable.

### EX-04 CSV first-column ingestion

1) Problem statement

CSV stage emits string table; downstream expects normalized float.

2) Raw source command(s)

~~~text
µ> printf 'score,name\n64,api\n'
~~~

3) Target consumer command(s)

~~~text
µ> render_float
~~~

4) Mismatch diagnosis

CSV_Data to Float_Normalized mismatch.

5) Synthesized transformation sketch

~~~text
lambda x: float(x.splitlines()[1].split(',')[0]) / 100.0
~~~

6) Verification result

~~~text
Z3_PROOF_PASS True
~~~

7) Final working command sequence

~~~text
µ> printf 'score,name\n64,api\n' | render_float
~~~

8) Expected output snippet

~~~text
>>> [RENDERED UI]: 0.64
~~~

9) Production hardening notes

- Prefer dedicated CSV parser stage over split-based extraction.
- Pin column order in upstream exporter contract.

### EX-05 DevOps health ratio bridge with cache warm-up

1) Problem statement

Health check stage emits integer percentage repeatedly.

2) Raw source command(s)

~~~text
µ> echo 99
~~~

3) Target consumer command(s)

~~~text
µ> render_float
~~~

4) Mismatch diagnosis

Plaintext to Float_Normalized mismatch.

5) Synthesized transformation sketch

~~~text
lambda x: float(x.strip()) / 100.0
~~~

6) Verification result

~~~text
Run 1: verification passed and cached
Run 2+: cache hit path
~~~

7) Final working command sequence

~~~text
µ> echo 99 | render_float
~~~

8) Expected output snippet

~~~text
>>> [RENDERED UI]: 0.99
~~~

9) Production hardening notes

- This is a hot-path candidate; keep boundary stable to maximize cache hits.

## Intermediate Track (multi-stage workflows)

### EX-06 Strict schema v1 pinned transform

1) Problem statement

API contract v1 requires explicit, audited transform logic.

2) Raw source command(s)

~~~bash
python - <<'PY'
import asyncio
from morphism.core.node import FunctorNode
from morphism.core.pipeline import MorphismPipeline
from morphism.core.schemas import Schema, Float_Normalized, String_NonEmpty

API_V1 = Schema('API_V1_Score', str, 'len(x) > 0')
source = FunctorNode(API_V1, API_V1, lambda _: '{"schema":"v1","score":70}', 'api_v1_source')
pinned = FunctorNode(API_V1, Float_Normalized, lambda x: float(__import__('json').loads(x)['score'])/100.0, 'Pinned_v1_Bridge')
consumer = FunctorNode(Float_Normalized, String_NonEmpty, lambda x: f'[RENDERED UI]: {x}', 'render_float')

p = MorphismPipeline(llm_client=None)

async def run():
    await p.append(source)
    await p.append(pinned)
    await p.append(consumer)
    print(await p.execute_all(None))

asyncio.run(run())
PY
~~~

3) Target consumer command(s)

~~~text
render_float equivalent node in API pipeline
~~~

4) Mismatch diagnosis

No synthesis mismatch allowed; bridge is explicit.

5) Synthesized transformation sketch

~~~text
Not used. Explicit pinned transform.
~~~

6) Verification result

~~~text
Optional explicit verifier call can be run in build checks; runtime path is deterministic
~~~

7) Final working command sequence

~~~text
api_v1_source -> Pinned_v1_Bridge -> render_float
~~~

8) Expected output snippet

~~~text
[RENDERED UI]: 0.7
~~~

9) Production hardening notes

- Version pin enforced by schema name API_V1_Score.
- Keep v1 and v2 bridges side-by-side for migration safety.

### EX-07 Strict schema v2 pinned transform

1) Problem statement

API contract v2 moved score field to metrics.score.

2) Raw source command(s)

~~~bash
python - <<'PY'
import asyncio
from morphism.core.node import FunctorNode
from morphism.core.pipeline import MorphismPipeline
from morphism.core.schemas import Schema, Float_Normalized, String_NonEmpty

API_V2 = Schema('API_V2_Metrics', str, 'len(x) > 0')
source = FunctorNode(API_V2, API_V2, lambda _: '{"schema":"v2","metrics":{"score":73}}', 'api_v2_source')
pinned = FunctorNode(API_V2, Float_Normalized, lambda x: float(__import__('json').loads(x)['metrics']['score'])/100.0, 'Pinned_v2_Bridge')
consumer = FunctorNode(Float_Normalized, String_NonEmpty, lambda x: f'[RENDERED UI]: {x}', 'render_float')

p = MorphismPipeline(llm_client=None)

async def run():
    await p.append(source)
    await p.append(pinned)
    await p.append(consumer)
    print(await p.execute_all(None))

asyncio.run(run())
PY
~~~

3) Target consumer command(s)

~~~text
render_float equivalent node in API pipeline
~~~

4) Mismatch diagnosis

No runtime synthesis allowed on pinned compliance boundary.

5) Synthesized transformation sketch

~~~text
Not used. Explicit pinned transform for v2.
~~~

6) Verification result

~~~text
Verifier can be executed in CI as policy gate on pinned bridge
~~~

7) Final working command sequence

~~~text
api_v2_source -> Pinned_v2_Bridge -> render_float
~~~

8) Expected output snippet

~~~text
[RENDERED UI]: 0.73
~~~

9) Production hardening notes

- Keep schema names versioned and immutable.
- Block fallback synthesis on pinned boundaries in policy wrapper.

### EX-08 Event severity routing guard

1) Problem statement

Only severity values from 0 to 100 should reach float consumer.

2) Raw source command(s)

~~~text
µ> echo '{"severity": 120}'
~~~

3) Target consumer command(s)

~~~text
µ> render_float
~~~

4) Mismatch diagnosis

Potential out-of-range severity; unsafe direct normalization.

5) Synthesized transformation sketch

~~~text
Reject candidate that can output > 1.0; require clamped or guarded strategy
~~~

6) Verification result

~~~text
Initial transform rejected; guarded transform accepted
~~~

7) Final working command sequence

~~~text
µ> echo '{"severity": 120}' | python -c "import sys,json; d=json.load(sys.stdin); print(min(max(d['severity'],0),100))" | render_float
~~~

8) Expected output snippet

~~~text
>>> [RENDERED UI]: 1.0
~~~

9) Production hardening notes

- Keep guard logic explicit for safety-critical metrics.

### EX-09 CLI to DB ingestion statement builder

1) Problem statement

Transform JSON event into SQL insert statement payload.

2) Raw source command(s)

~~~text
µ> echo '{"id":42,"score":88}'
~~~

3) Target consumer command(s)

~~~text
µ> python -c "import sys; x=sys.stdin.read().strip(); print('INSERT INTO scores(payload) VALUES (' + repr(x) + ');')"
~~~

4) Mismatch diagnosis

JSON_Object producer to Plaintext SQL builder can run directly but often requires field normalization.

5) Synthesized transformation sketch

~~~text
lambda x: __import__('json').loads(x)['score'] / 100.0 then format downstream
~~~

6) Verification result

~~~text
Boundary to normalized score consumer verified before SQL formatting stage
~~~

7) Final working command sequence

~~~text
µ> echo '{"id":42,"score":88}' | render_float | python -c "import sys; print('metric=' + sys.stdin.read().strip())"
~~~

8) Expected output snippet

~~~text
>>> metric=[RENDERED UI]: 0.88
~~~

9) Production hardening notes

- Keep SQL construction in dedicated parameterized sink outside ad-hoc shell.

### EX-10 Compliance audit export normalization with cache

1) Problem statement

Audit export emits repetitive payload shape; repeated runs should avoid repeated synthesis.

2) Raw source command(s)

~~~text
µ> echo '{"audit_score": 91}'
~~~

3) Target consumer command(s)

~~~text
µ> render_float
~~~

4) Mismatch diagnosis

JSON_Object to Float_Normalized mismatch.

5) Synthesized transformation sketch

~~~text
lambda x: float(__import__('json').loads(x)['audit_score']) / 100.0
~~~

6) Verification result

~~~text
Run 1 verified and stored
Run 2 shows cache hit behavior for same schema boundary
~~~

7) Final working command sequence

~~~text
µ> echo '{"audit_score": 91}' | render_float
~~~

8) Expected output snippet

~~~text
>>> [RENDERED UI]: 0.91
~~~

9) Production hardening notes

- Use fixed key names and schema shape in exporter.
- Keep cache DB persisted between scheduled runs if warm path is desired.

### EX-11 Branch fan-out readiness checks

1) Problem statement

Single health value feeds two independent consumers.

2) Raw source command(s)

~~~text
µ> emit_raw
~~~

3) Target consumer command(s)

~~~text
µ> render_float and another render_float branch
~~~

4) Mismatch diagnosis

Each branch must satisfy same boundary constraints.

5) Synthesized transformation sketch

~~~text
Same bridge strategy reused across sibling edges
~~~

6) Verification result

~~~text
Per-edge verification pass required; cache can reduce duplicate synthesis work
~~~

7) Final working command sequence

~~~text
µ> emit_raw |+ (render_float, render_float)
~~~

8) Expected output snippet

~~~text
>>> [RENDERED UI]: 0.5
~~~

9) Production hardening notes

- Validate branch consumers are idempotent because they may run concurrently.

## Advanced Track (high-assurance and scale)

### EX-12 Intentional verification failure then correction

1) Problem statement

Unsafe target demands Int_0_to_10 from Int_0_to_100 without clamp.

2) Raw source command(s)

~~~bash
python - <<'PY'
import asyncio
from morphism.ai.synthesizer import MockLLMSynthesizer
from morphism.core.cache import FunctorCache
from morphism.core.node import FunctorNode
from morphism.core.pipeline import MorphismPipeline
from morphism.core.schemas import Int_0_to_100, Int_0_to_10, String_NonEmpty
from morphism.exceptions import VerificationFailedError

emit = FunctorNode(Int_0_to_100, Int_0_to_100, lambda x: 50, 'emit_raw')
strict = FunctorNode(Int_0_to_10, String_NonEmpty, lambda x: f'strict:{x}', 'strict_consumer')
p = MorphismPipeline(llm_client=MockLLMSynthesizer(), cache=FunctorCache())

async def run():
    await p.append(emit)
    try:
        await p.append(strict)
    except VerificationFailedError as e:
        print('VERIFY_FAIL')
        print(e)

asyncio.run(run())
PY
~~~

3) Target consumer command(s)

~~~text
strict_consumer requiring Int_0_to_10
~~~

4) Mismatch diagnosis

Generated candidate cannot prove target bounded to 0..10.

5) Synthesized transformation sketch

~~~text
Initial unsafe candidate rejected
Correction: explicit clamp lambda x: max(0, min(10, int(x/10)))
~~~

6) Verification result

~~~text
Initial: fail
Corrected pinned transform: pass
~~~

7) Final working command sequence

~~~bash
python - <<'PY'
import asyncio
from morphism.core.node import FunctorNode
from morphism.core.pipeline import MorphismPipeline
from morphism.core.schemas import Int_0_to_100, Int_0_to_10, String_NonEmpty

emit = FunctorNode(Int_0_to_100, Int_0_to_100, lambda x: 50, 'emit_raw')
bridge = FunctorNode(Int_0_to_100, Int_0_to_10, lambda x: max(0, min(10, int(x/10))), 'Pinned_Clamp')
strict = FunctorNode(Int_0_to_10, String_NonEmpty, lambda x: f'strict:{x}', 'strict_consumer')
p = MorphismPipeline(llm_client=None)

async def run():
    await p.append(emit)
    await p.append(bridge)
    await p.append(strict)
    print(await p.execute_all(None))

asyncio.run(run())
PY
~~~

8) Expected output snippet

~~~text
strict:5
~~~

9) Production hardening notes

- Use pinned clamp bridges for strict bounded compliance domains.

### EX-13 Verification failure on malformed plaintext parse

1) Problem statement

Producer emits non-numeric plaintext to numeric consumer.

2) Raw source command(s)

~~~text
µ> echo 'score=abc'
~~~

3) Target consumer command(s)

~~~text
µ> render_float
~~~

4) Mismatch diagnosis

Parse cannot produce valid float; candidates fail dry-run or verifier checks.

5) Synthesized transformation sketch

~~~text
Unsafe parse candidate rejected
Correction: guarded parser with default fallback value
~~~

6) Verification result

~~~text
Initial candidate rejected
Guarded stage then verified boundary accepted
~~~

7) Final working command sequence

~~~text
µ> echo 'score=abc' | python -c "import sys,re; s=sys.stdin.read(); m=re.search(r'(\d+)', s); print(m.group(1) if m else 0)" | render_float
~~~

8) Expected output snippet

~~~text
>>> [RENDERED UI]: 0.0
~~~

9) Production hardening notes

- Never trust free-form plaintext at numeric boundaries without guard stage.

### EX-14 Enterprise-safe policy-constrained execution

1) Problem statement

Only approved schema-pair transforms may run in production.

2) Raw source command(s)

~~~bash
python - <<'PY'
import asyncio
from morphism.ai.synthesizer import MockLLMSynthesizer
from morphism.core.cache import FunctorCache
from morphism.core.node import FunctorNode
from morphism.core.pipeline import MorphismPipeline
from morphism.core.schemas import Int_0_to_100, Float_Normalized, String_NonEmpty

ALLOWLIST = {('Int_0_to_100', 'Float_Normalized')}

def policy_check(src, tgt):
    if (src.name, tgt.name) not in ALLOWLIST:
        raise RuntimeError('POLICY_DENY')

class PolicyPipeline(MorphismPipeline):
    async def _resolve_mismatch(self, node_a, node_b):
        policy_check(node_a.output_schema, node_b.input_schema)
        return await super()._resolve_mismatch(node_a, node_b)

emit = FunctorNode(Int_0_to_100, Int_0_to_100, lambda x: 50, 'emit_raw')
render = FunctorNode(Float_Normalized, String_NonEmpty, lambda x: f'[RENDERED UI]: {x}', 'render_float')
p = PolicyPipeline(llm_client=MockLLMSynthesizer(), cache=FunctorCache())

async def run():
    await p.append(emit)
    await p.append(render)
    print(await p.execute_all(None))

asyncio.run(run())
PY
~~~

3) Target consumer command(s)

~~~text
render_float under policy allowlist
~~~

4) Mismatch diagnosis

Mismatches outside allowlist are denied before synthesis.

5) Synthesized transformation sketch

~~~text
Allowed pair uses standard normalized bridge strategy
~~~

6) Verification result

~~~text
Allowed boundary verified and executed
Denied boundaries fail with POLICY_DENY
~~~

7) Final working command sequence

~~~text
PolicyPipeline: emit_raw -> AI_Bridge_Functor -> render_float
~~~

8) Expected output snippet

~~~text
[RENDERED UI]: 0.5
~~~

9) Production hardening notes

- Integrate allowlist with change-managed config and audit logging.

### EX-15 Deterministic CI batch pipeline

1) Problem statement

Need non-interactive deterministic verification in CI.

2) Raw source command(s)

~~~bash
export MORPHISM_MAX_SYNTHESIS_ATTEMPTS=1
export MORPHISM_Z3_TIMEOUT_MS=2000
export MORPHISM_LLM_REQUEST_TIMEOUT=30
~~~

3) Target consumer command(s)

~~~bash
python ci_morphism_runner.py
~~~

4) Mismatch diagnosis

CI runner must fail fast with stable exit contract.

5) Synthesized transformation sketch

~~~text
Use deterministic synthesizer or pinned transforms in CI path
~~~

6) Verification result

~~~text
CI_SMOKE_PASS with explicit assertion and exit code 0
~~~

7) Final working command sequence

~~~bash
python - <<'PY'
import asyncio, sys
from morphism.ai.synthesizer import MockLLMSynthesizer
from morphism.core.cache import FunctorCache
from morphism.core.node import FunctorNode
from morphism.core.pipeline import MorphismPipeline
from morphism.core.schemas import Int_0_to_100, Float_Normalized, String_NonEmpty

emit = FunctorNode(Int_0_to_100, Int_0_to_100, lambda x: 50, 'emit_raw')
render = FunctorNode(Float_Normalized, String_NonEmpty, lambda x: f'[RENDERED UI]: {x}', 'render_float')
p = MorphismPipeline(llm_client=MockLLMSynthesizer(), cache=FunctorCache())

async def run():
    await p.append(emit)
    await p.append(render)
    out = await p.execute_all(None)
    if out != '[RENDERED UI]: 0.5':
        return 1
    print('CI_SMOKE_PASS')
    return 0

sys.exit(asyncio.run(run()))
PY
~~~

8) Expected output snippet

~~~text
CI_SMOKE_PASS
~~~

9) Production hardening notes

- Archive logs/morphism.log and .morphism_cache.db as CI artifacts for triage.

## Failure-and-Recovery Cases

Case FR-1 (from EX-12): strict bounded target fails verification

Triage:

1. Confirm source and target constraint mismatch.
2. Inspect rejection reason in verification error message.
3. Introduce explicit clamped pinned transform.

Case FR-2 (from EX-13): malformed plaintext numeric extraction

Triage:

1. Add guard parser stage.
2. Route invalid payloads to safe default or dead-letter path.
3. Re-run verification on guarded boundary.

Case FR-3 (policy-driven) (from EX-14)

Triage:

1. POLICY_DENY indicates governance block, not runtime bug.
2. Submit allowlist change or refactor boundary to approved schema pair.

## CI/Automation Cases

### Non-interactive deterministic run template

~~~bash
export MORPHISM_LOG_LEVEL=DEBUG
export MORPHISM_MAX_SYNTHESIS_ATTEMPTS=1
export MORPHISM_Z3_TIMEOUT_MS=2000
python -c "from pathlib import Path; Path('.morphism_cache.db').unlink(missing_ok=True)"
python ci_morphism_runner.py
~~~

### Warm-cache performance regression template

~~~bash
python ci_morphism_runner.py
python ci_morphism_runner.py
python -c "import sqlite3; c=sqlite3.connect('.morphism_cache.db'); print(c.execute('select count(*) from functors').fetchone()[0]); c.close()"
~~~

Expected behavior:

- First run may synthesize.
- Second run should prefer cache path for repeated schema pairs.

### Verification-failure gate template

~~~bash
python ci_morphism_negative_case.py
test $? -ne 0
~~~

Expected behavior:

- Build fails when boundary cannot be safely repaired.

## Pattern Summary + Recommended Starting Templates

Start template T1: interactive exploration

~~~text
µ> emit_raw | render_float
µ> history
µ> inspect 2
~~~

Use when:

- debugging boundary behavior locally.

Start template T2: pinned-transform production path

~~~python
# source -> pinned bridge -> consumer
~~~

Use when:

- regulatory or deterministic boundary control required.

Start template T3: CI deterministic smoke

~~~bash
python ci_morphism_runner.py
~~~

Use when:

- pipeline contract enforcement in pull requests and deploy gates.

Start template T4: policy-governed enterprise execution

~~~python
# subclass MorphismPipeline and enforce schema-pair allowlist in _resolve_mismatch
~~~

Use when:

- transformation admission must follow governance policy.
