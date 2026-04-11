---
title: Morphism Engine CLI Usage
description: Command-first operational manual for Morphism Engine CLI behavior, IO semantics, automation, and failure handling.
slug: /cli-usage
---

## CLI Synopsis

Version scope: Morphism Engine 3.1.x.

Command synopsis table:

| Command | Purpose | Invocation | Positional Args | Process Flags |
|---|---|---|---|---|
| morphism | Interactive REPL (typed pipelines) | `morphism` | none | none |
| morphism-tui | Textual UI | `morphism-tui` | none | none |
| morphism-engine | Alias of TUI | `morphism-engine` | none | none |
| python module path | Direct module launch | `python -m morphism.cli.shell` | none | none |

Invocation model:

1. Start process with no arguments.
2. Enter pipeline expressions at prompt (`morphism`) or command bar (TUI).
3. Engine parses linear and branched forms.
4. Execution result prints as `>>> <value>`.

Grammar accepted by current shell parser:

- Linear pipeline: `cmd_a | cmd_b | cmd_c`
- Branch fan-out: `cmd_a |+ (cmd_b, cmd_c, cmd_d)`

Built-in REPL commands:

- `history`
- `inspect <node_number>`
- `tools`
- `help`
- `quit` / `exit` / `Ctrl-D`

Stdin/stdout/stderr behavior:

- REPL command input is line-oriented from terminal session, not streaming stdin protocol.
- Success output is written to stdout as `>>> ...`.
- Handled pipeline errors are also printed by shell to stdout as `[Morphism] ERROR: ...`.
- Logger console handler emits log records through Python logging StreamHandler (typically stderr).

Flag precedence:

- There are no process flags in 3.1.x.
- Runtime behavior is controlled via environment variables only.

## Input/Output Semantics

### Input modes

Inline payloads:

- Primary mode. Pipeline text entered directly at prompt.
- Example: `emit_raw | render_float`.

Streamed stdin:

- Not a first-class CLI mode in 3.1.x.
- Workaround: use native command nodes that themselves consume stdin from upstream command output.

File-based inputs:

- Supported through native commands in pipeline expression.
- Example: `type data.json | python -c "..."` (Windows) or `cat data.json | python -c "..."` (POSIX).

Mixed sources and conflict resolution:

- Shell parser splits by `|` and `|+` first.
- Unknown segments become native subprocess nodes.
- Actual source precedence is determined by command ordering in the expression.
- No explicit source arbitration flags exist.

### Output modes

Human-readable output:

- Default and only native CLI mode in 3.1.x.
- Result line format: `>>> <result>`.

Machine-readable output:

- No dedicated JSON output flag exists.
- For machine contracts, emit JSON from your pipeline nodes (native command or custom tool) and parse externally.

Verbosity levels:

- Controlled by `MORPHISM_LOG_LEVEL` environment variable.
- Values map to Python logging levels (`DEBUG`, `INFO`, etc.).

Error output contract:

- Handled engine exceptions: prefixed line with `[Morphism] ERROR:`.
- Unexpected exceptions: `[Morphism] UNEXPECTED ERROR:`.
- Native subprocess failure includes exit code and stderr text when available.

## Options and Flags (reference table)

Process-level options and flags (3.1.x):

| Name | Type | Default | Behavior | Failure Mode |
|---|---|---|---|---|
| (none) | n/a | n/a | No process flags are currently implemented for `morphism`, `morphism-tui`, or `morphism-engine`. | Passing extra args may be interpreted by Python launcher/shell, not Morphism. |

Runtime control surface (environment controls used in place of flags):

| Name | Type | Default | Behavior | Failure Mode |
|---|---|---|---|---|
| MORPHISM_OLLAMA_URL | string URL | `http://localhost:11434/api/generate` | LLM synthesis endpoint | Connection errors and synthesis timeout on mismatch repair |
| MORPHISM_MODEL_NAME | string | `qwen2.5-coder:1.5b` | Target model for synthesis | Poor/invalid transforms, increased retries |
| MORPHISM_Z3_TIMEOUT_MS | int | `2000` | SMT solver timeout per verification | `unknown` can escalate to verification failure |
| MORPHISM_LOG_LEVEL | string | `INFO` | Console log verbosity | Invalid value falls back to INFO behavior |
| MORPHISM_MAX_SYNTHESIS_ATTEMPTS | int | `6` | Candidate retry budget per mismatch | Exhaustion returns verification failure |
| MORPHISM_LLM_REQUEST_TIMEOUT | int seconds | `60` | HTTP timeout for synthesis request | Timeout and eventual synthesis failure |

## Execution + Verification Modes

Current execution modes:

- Interactive REPL mode (`morphism`)
- Interactive TUI mode (`morphism-tui`, `morphism-engine`)

Dry-run:

- Not available as CLI flag in 3.1.x.
- Workaround: construct pipeline using API and stop before `execute_all`.

Explain/debug mode:

- No dedicated explain flag.
- Use `MORPHISM_LOG_LEVEL=DEBUG` plus `history` and `inspect` commands.

Strict mode:

- No strict-mode flag.
- Approximation: enforce deterministic synthesis backend in automation and fail on any repair event via wrapper logic.

Timeout/retry controls:

- Configured via environment variables (`MORPHISM_LLM_REQUEST_TIMEOUT`, `MORPHISM_Z3_TIMEOUT_MS`, `MORPHISM_MAX_SYNTHESIS_ATTEMPTS`).

Non-interactive mode for CI:

- No direct non-interactive CLI switch.
- Recommended: invoke pipeline through Python API snippet and emit explicit exit codes.

Verification controls:

- Verification is mandatory for synthesized bridges in current implementation.
- No CLI option to bypass verification.
- If verification fails, bridge insertion is blocked and execution fails at that boundary.

Verification status outputs:

- Status is surfaced via logger lines (INFO/DEBUG) and final success/failure outcome.

## Caching + Determinism

CLI-visible cache behavior:

- Cache lookup occurs automatically on schema mismatch.
- Cache key is schema-pair based (`source_name::target_name`, hashed in storage).
- Cache entries are recompiled and re-verified before use.

Cache bypass/refresh options:

- No CLI flag for bypass/refresh in 3.1.x.
- Operational methods:
  - delete `.morphism_cache.db` to force cold path;
  - change schema boundary to generate distinct key.

Deterministic rerun behavior:

- Warm-path determinism improves when cache entry exists and passes verification.
- Cold-path determinism depends on LLM backend; for strict reproducibility, use deterministic synthesizer in automation tests.

## Config + Environment Precedence

Precedence model in 3.1.x:

1. Environment variables (`MORPHISM_*`)
2. Built-in defaults in configuration dataclass

Not implemented:

- CLI flag overrides
- Config file loading
- Profile selection

Implication:

- Any script requiring immutable behavior must set env explicitly in execution wrapper.

## Exit Codes

Important: stock interactive CLI does not currently emit granular process exit codes for handled pipeline failures; many command-level failures are printed and the process continues.

Observed process-level behavior:

| Code | Meaning in stock CLI |
|---|---|
| 0 | Normal process termination (including sessions where some commands failed but were handled in-session) |
| non-zero | Unhandled launcher/runtime failure before or outside normal error handling |

Recommended normalized exit code contract for automation wrappers:

| Code | Meaning |
|---|---|
| 0 | success |
| 10 | synthesis failure (timeout/network/backend) |
| 11 | verification failure (candidate rejected/exhausted) |
| 12 | config error (invalid env or missing required runtime config) |
| 13 | runtime execution error (native command/process/node failure) |
| 14 | usage/grammar error |

## Automation and CI Patterns

Use non-interactive wrappers to obtain deterministic logs and explicit exit codes.

### CI snippet 1: deterministic env bootstrap (bash)

```bash
export MORPHISM_LOG_LEVEL=DEBUG
export MORPHISM_MAX_SYNTHESIS_ATTEMPTS=1
export MORPHISM_Z3_TIMEOUT_MS=2000
export MORPHISM_LLM_REQUEST_TIMEOUT=30
python -c "from pathlib import Path; Path('.morphism_cache.db').unlink(missing_ok=True)"
```

Expected output:

```text
(no output on success)
```

### CI snippet 2: explicit wrapper with normalized exit codes

```bash
python - <<'PY'
import asyncio
import sys
from morphism.ai.synthesizer import MockLLMSynthesizer
from morphism.core.cache import FunctorCache
from morphism.core.node import FunctorNode
from morphism.core.pipeline import MorphismPipeline
from morphism.core.schemas import Int_0_to_100, Float_Normalized, String_NonEmpty
from morphism.exceptions import SynthesisTimeoutError, VerificationFailedError, EngineExecutionError

async def run() -> int:
    emit = FunctorNode(Int_0_to_100, Int_0_to_100, lambda x: 50, "emit_raw")
    render = FunctorNode(Float_Normalized, String_NonEmpty, lambda x: f"[RENDERED UI]: {x}", "render_float")
    p = MorphismPipeline(llm_client=MockLLMSynthesizer(), cache=FunctorCache())
    try:
        await p.append(emit)
        await p.append(render)
        out = await p.execute_all(None)
        print(out)
        return 0
    except SynthesisTimeoutError:
        return 10
    except VerificationFailedError:
        return 11
    except EngineExecutionError:
        return 13
    except Exception:
        return 14

sys.exit(asyncio.run(run()))
PY
```

Expected output:

```text
[RENDERED UI]: 0.5
```

Expected exit code:

```text
0
```

### 12+ realistic command examples

1. Launch REPL.

```bash
morphism
```

Expected output:

```text
... Morphism ...
µ>
```

2. List built-in tools.

```text
µ> tools
```

Expected output:

```text
[Morphism] Registered tools:
  emit_raw              None (source) -> Int_0_to_100
  render_float          Float_Normalized -> String_NonEmpty
```

3. Run source tool only.

```text
µ> emit_raw
```

Expected output:

```text
>>> 50
```

4. Run repaired linear pipeline.

```text
µ> emit_raw | render_float
```

Expected output:

```text
>>> [RENDERED UI]: 0.5
```

5. View pipeline history.

```text
µ> history
```

Expected output:

```text
(1) emit_raw -> (2) AI_Bridge_Functor -> (3) render_float
```

6. Inspect bridge node.

```text
µ> inspect 2
```

Expected output:

```text
[Node 2] AI_Bridge_Functor
  Schema : Int_0_to_100 -> Float_Normalized
  State  : 0.5
```

7. Branch fan-out.

```text
µ> emit_raw |+ (render_float, render_float)
```

Expected output:

```text
>>> [RENDERED UI]: 0.5
```

8. Unknown tool fallback to native command.

```text
µ> echo 42
```

Expected output:

```text
>>> 42
```

9. Native command failure surface.

```text
µ> nonexistent_tool | render_float
```

Expected output:

```text
[Morphism] ERROR: Command 'nonexistent_tool' exited with code ...
```

10. Invalid inspect argument.

```text
µ> inspect x
```

Expected output:

```text
[Morphism] Usage: inspect <node number>
```

11. Out-of-range inspect.

```text
µ> inspect 99
```

Expected output:

```text
[Morphism] Node 99 does not exist. Pipeline has ... node(s).
```

12. Exit shell via command.

```text
µ> quit
```

Expected output:

```text
[Morphism] Goodbye.
```

13. Launch TUI alias.

```bash
morphism-engine
```

Expected output:

```text
TUI starts with command input and telemetry panes.
```

14. Launch TUI canonical command.

```bash
morphism-tui
```

Expected output:

```text
TUI starts with command input and telemetry panes.
```

### Quoting and shell-safety patterns

Bash/zsh JSON with embedded quotes:

```bash
morphism
# then in REPL
echo '{"name":"Ada","score":85}' | python -c "import sys,json; d=json.load(sys.stdin); print(d['score'])"
```

fish:

```fish
morphism
# then in REPL
echo '{"name":"Ada"}' ^| python -c "import sys,json; print(json.load(sys.stdin)['name'])"
```

PowerShell:

```powershell
morphism
# then in REPL
echo '{"name":"Ada","score":85}' | python -c "import sys,json; d=json.load(sys.stdin); print(d['score'])"
```

Caveat:

- Parser splits on `|` before native command interpretation. If your native command itself needs literal pipe symbols, wrap the logic in an external script and call that script as a single command token.

## Troubleshooting

Tie failures to exit codes and diagnostics.

| Symptom | Likely Code | Diagnostic Command | Resolution |
|---|---|---|---|
| Wrapper returns 10 | 10 synthesis failure | `python -c "import os; print(os.getenv('MORPHISM_OLLAMA_URL'))"` | fix endpoint/model connectivity; increase request timeout |
| Wrapper returns 11 | 11 verification failure | inspect logs: `logs/morphism.log` | adjust schema boundary or transform strategy; raise attempt budget cautiously |
| Wrapper returns 12 | 12 config error | `python -c "from morphism.config import config; print(config)"` | correct malformed env values |
| Wrapper returns 13 | 13 runtime error | rerun with `MORPHISM_LOG_LEVEL=DEBUG` | repair failing native command/node logic |
| Wrapper returns 14 | 14 usage error | validate grammar against linear/branch forms | fix command syntax |
| Interactive CLI shows error but process still exits 0 | 0 process exit | inspect in-session output and logs | use wrapper mode for script-grade status signaling |

Operational caveats for production scripts:

1. Do not rely on stock interactive process exit code for per-command success/failure semantics.
2. Set all relevant `MORPHISM_*` env vars explicitly in automation jobs.
3. Clear or preserve `.morphism_cache.db` intentionally depending on cold-path vs warm-path test goals.
4. Capture `logs/morphism.log` as CI artifact for post-failure triage.
