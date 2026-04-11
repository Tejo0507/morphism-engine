---
title: Morphism Engine Quick Start
description: 5-minute end-to-end proof of Morphism detecting a broken boundary, synthesizing a bridge, proving it with Z3, and executing with cache acceleration.
slug: /quick-start
---

## What You'll Build in 5 Minutes

Time to complete: 5-8 minutes.

You will run a deterministic, copy-paste walkthrough that proves all critical mechanics:

1. A pipeline fails at a type boundary.
2. Morphism synthesizes a bridge function.
3. Z3 proof gate approves the bridge.
4. Corrected pipeline executes.
5. Second run reuses cache (no synthesis call).

This walkthrough uses Morphism's `MockLLMSynthesizer` so it is reproducible and does not require Ollama.

## Prerequisites Check

Run from repo root.

```bash
python -c "import sys; print('PYTHON', sys.version.split()[0])"
python -c "import morphism; print('MORPHISM_IMPORT_OK')"
python -c "import z3; print('Z3_OK', z3.get_version_string())"
```

Expected Output:

```text
PYTHON 3.11.x
MORPHISM_IMPORT_OK
Z3_OK <version>
```

If imports fail, install first using the installation guide.

## Broken Pipeline Reproduction

This simulates a producer/consumer boundary mismatch:

- Producer: `emit_raw` outputs `Int_0_to_100`
- Consumer: `render_float` requires `Float_Normalized`

Step 1: run pipeline construction without synthesis.

```bash
python - <<'PY'
import asyncio
from morphism.core.node import FunctorNode
from morphism.core.pipeline import MorphismPipeline
from morphism.core.schemas import Int_0_to_100, Float_Normalized, String_NonEmpty
from morphism.exceptions import SchemaMismatchError

emit = FunctorNode(
	input_schema=Int_0_to_100,
	output_schema=Int_0_to_100,
	executable=lambda x: 50,
	name="emit_raw",
)
render = FunctorNode(
	input_schema=Float_Normalized,
	output_schema=String_NonEmpty,
	executable=lambda x: f"[RENDERED UI]: {x}",
	name="render_float",
)

pipeline = MorphismPipeline(llm_client=None)

async def main() -> None:
	await pipeline.append(emit)
	try:
		await pipeline.append(render)
		print("UNEXPECTED_PASS")
	except SchemaMismatchError as e:
		print("FAIL_BOUNDARY")
		print(str(e))

asyncio.run(main())
PY
```

Expected Output:

```text
FAIL_BOUNDARY
TYPE MISMATCH: Cannot pipe FunctorNode('emit_raw', in=Int_0_to_100, out=Int_0_to_100) to FunctorNode('render_float', in=Float_Normalized, out=String_NonEmpty)
```

Step 2: inspect mismatch/type diagnostics (from the same output):

- `source output schema`: `Int_0_to_100`
- `target input schema`: `Float_Normalized`
- `gate decision`: reject direct link

## Synthesis + Verification Walkthrough

Step 3: run Morphism synthesis path on the same boundary, with cache reset.

```bash
python - <<'PY'
import asyncio
import sqlite3
from pathlib import Path

from morphism.ai.synthesizer import MockLLMSynthesizer
from morphism.core.cache import FunctorCache
from morphism.core.node import FunctorNode
from morphism.core.pipeline import MorphismPipeline
from morphism.core.schemas import Int_0_to_100, Float_Normalized, String_NonEmpty

Path(".morphism_cache.db").unlink(missing_ok=True)

emit = FunctorNode(
	input_schema=Int_0_to_100,
	output_schema=Int_0_to_100,
	executable=lambda x: 50,
	name="emit_raw",
)
render = FunctorNode(
	input_schema=Float_Normalized,
	output_schema=String_NonEmpty,
	executable=lambda x: f"[RENDERED UI]: {x}",
	name="render_float",
)

pipeline = MorphismPipeline(llm_client=MockLLMSynthesizer(), cache=FunctorCache())

async def main() -> None:
	await pipeline.append(emit)
	await pipeline.append(render)
	result = await pipeline.execute_all(None)
	print("RUN1_RESULT", result)
	print("RUN1_NODES", [n.name for n in pipeline.all_nodes])

asyncio.run(main())

conn = sqlite3.connect(".morphism_cache.db")
row = conn.execute("SELECT source_name, target_name, lambda_string FROM functors").fetchone()
conn.close()
print("CACHE_ROW", row)
PY
```

Expected Output:

```text
RUN1_RESULT [RENDERED UI]: 0.5
RUN1_NODES ['emit_raw', 'AI_Bridge_Functor', 'render_float']
CACHE_ROW ('Int_0_to_100', 'Float_Normalized', 'lambda x: x / 100.0')
```

Step 4: review generated transformation artifact.

From `CACHE_ROW`, generated bridge code is:

```text
lambda x: x / 100.0
```

Step 5: run explicit Z3-backed verification on that artifact.

```bash
python - <<'PY'
import sqlite3

from morphism.math.z3_verifier import verify_functor_mapping
from morphism.core.schemas import Int_0_to_100, Float_Normalized

conn = sqlite3.connect('.morphism_cache.db')
code = conn.execute(
	"SELECT lambda_string FROM functors "
	"WHERE source_name='Int_0_to_100' AND target_name='Float_Normalized'"
).fetchone()[0]
conn.close()

fn = eval(code)
ok = verify_functor_mapping(Int_0_to_100, Float_Normalized, fn, code_str=code)
print('BRIDGE_CODE', code)
print('Z3_PROOF_PASS', ok)
PY
```

Expected Output:

```text
BRIDGE_CODE lambda x: x / 100.0
Z3_PROOF_PASS True
```

Verification semantics:

- `True` means no satisfying counterexample exists for `0 <= x <= 100` that would violate target bounds `0.0 <= f(x) <= 1.0`.
- In other words, Z3 proved the bridge is safe for the schema contract.

## Successful Execution + Cache Demonstration

Step 6: execute corrected pipeline (already shown in `RUN1_RESULT`).

Step 7: run again with a synthesizer that intentionally fails if called. If run still succeeds, cache path is proven.

```bash
python - <<'PY'
import asyncio

from morphism.ai.synthesizer import LLMSynthesizer
from morphism.core.cache import FunctorCache
from morphism.core.node import FunctorNode
from morphism.core.pipeline import MorphismPipeline
from morphism.core.schemas import Int_0_to_100, Float_Normalized, String_NonEmpty

class FailIfCalledSynth(LLMSynthesizer):
	async def generate_functor(self, source, target):
		raise RuntimeError("LLM_SHOULD_NOT_BE_CALLED_ON_CACHE_HIT")

emit = FunctorNode(
	input_schema=Int_0_to_100,
	output_schema=Int_0_to_100,
	executable=lambda x: 50,
	name="emit_raw",
)
render = FunctorNode(
	input_schema=Float_Normalized,
	output_schema=String_NonEmpty,
	executable=lambda x: f"[RENDERED UI]: {x}",
	name="render_float",
)

pipeline = MorphismPipeline(llm_client=FailIfCalledSynth(), cache=FunctorCache())

async def main() -> None:
	await pipeline.append(emit)
	await pipeline.append(render)
	result = await pipeline.execute_all(None)
	print("RUN2_RESULT", result)
	print("CACHE_HIT_CONFIRMED", "AI_Bridge_Functor" in [n.name for n in pipeline.all_nodes])

asyncio.run(main())
PY
```

Expected Output:

```text
RUN2_RESULT [RENDERED UI]: 0.5
CACHE_HIT_CONFIRMED True
```

What changed between failure and success:

- Inferred boundary problem: producer emits integer-domain value, consumer requires normalized float domain.
- Selected strategy: synthesize linear normalization bridge `x / 100.0`.
- Proof result: Z3 discharges the mapping obligation, then Morphism permits execution.
- Second run: bridge loaded from SQLite cache, synthesis bypassed.

## Failure Path + Recovery

Example verification failure branch (unsafe bridge proposal rejected):

```bash
python - <<'PY'
import asyncio

from morphism.ai.synthesizer import MockLLMSynthesizer
from morphism.core.cache import FunctorCache
from morphism.core.node import FunctorNode
from morphism.core.pipeline import MorphismPipeline
from morphism.core.schemas import Int_0_to_100, Int_0_to_10, String_NonEmpty
from morphism.exceptions import VerificationFailedError

emit = FunctorNode(
	input_schema=Int_0_to_100,
	output_schema=Int_0_to_100,
	executable=lambda x: 50,
	name="emit_raw",
)
strict = FunctorNode(
	input_schema=Int_0_to_10,
	output_schema=String_NonEmpty,
	executable=lambda x: f"strict:{x}",
	name="strict_consumer",
)

pipeline = MorphismPipeline(llm_client=MockLLMSynthesizer(), cache=FunctorCache())

async def main() -> None:
	await pipeline.append(emit)
	try:
		await pipeline.append(strict)
	except VerificationFailedError as e:
		print("VERIFY_FAIL")
		print(str(e))

asyncio.run(main())
PY
```

Expected Output:

```text
VERIFY_FAIL
Functor F(Int_0_to_100 -> Int_0_to_10) failed verification after 6 attempt(s). Last error: Z3 rejected functor
```

Recovery options:

1. Narrow the producer output domain before crossing the boundary.
2. Replace consumer schema with one matching actual producer semantics.
3. Provide a deterministic, reviewed transform implementation and re-run proof.
4. Increase `MORPHISM_MAX_SYNTHESIS_ATTEMPTS` only after checking model quality.

## CI-Friendly Variant

Use deterministic settings and non-interactive execution.

```bash
export MORPHISM_MAX_SYNTHESIS_ATTEMPTS=1
export MORPHISM_Z3_TIMEOUT_MS=2000
export MORPHISM_LOG_LEVEL=DEBUG

python -c "from pathlib import Path; Path('.morphism_cache.db').unlink(missing_ok=True); print('CACHE_CLEARED')"

python - <<'PY'
import asyncio

from morphism.ai.synthesizer import MockLLMSynthesizer
from morphism.core.cache import FunctorCache
from morphism.core.node import FunctorNode
from morphism.core.pipeline import MorphismPipeline
from morphism.core.schemas import Int_0_to_100, Float_Normalized, String_NonEmpty

emit = FunctorNode(
	input_schema=Int_0_to_100,
	output_schema=Int_0_to_100,
	executable=lambda x: 50,
	name="emit_raw",
)
render = FunctorNode(
	input_schema=Float_Normalized,
	output_schema=String_NonEmpty,
	executable=lambda x: f"[RENDERED UI]: {x}",
	name="render_float",
)

pipeline = MorphismPipeline(llm_client=MockLLMSynthesizer(), cache=FunctorCache())

async def main() -> None:
	await pipeline.append(emit)
	await pipeline.append(render)
	result = await pipeline.execute_all(None)
	print("CI_SMOKE_PASS" if result == "[RENDERED UI]: 0.5" else "CI_SMOKE_FAIL")

asyncio.run(main())
PY
```

Expected Output:

```text
CACHE_CLEARED
CI_SMOKE_PASS
```

Where artifacts are stored and how to inspect:

- Bridge cache: `.morphism_cache.db`
- Runtime logs: `logs/morphism.log`

Inspect cache rows:

```bash
python -c "import sqlite3; conn=sqlite3.connect('.morphism_cache.db'); rows=conn.execute('SELECT source_name,target_name,lambda_string,timestamp FROM functors').fetchall(); conn.close(); print(rows)"
```

Inspect recent proof/log activity:

```bash
tail -n 50 logs/morphism.log
```

## Where to Go Next

- Installation: [Installation](./installation.md)
- CLI shell implementation: [CLI Shell](../src/morphism/cli/shell.py)
- TUI implementation: [CLI TUI](../src/morphism/cli/tui.py)
- Pipeline core: [Pipeline](../src/morphism/core/pipeline.py)
