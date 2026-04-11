---
title: Morphism Engine CLI Reference
slug: /cli-reference
description: Exhaustive command and runtime reference for Morphism Engine CLI, including invocation grammar, IO contracts, environment controls, and failure semantics.
---

## Synopsis

Morphism Engine 3.1.x exposes three entrypoint commands and an interactive command language.
No process-level CLI flags, subcommands, or config-file loaders are currently implemented.
Runtime behavior is controlled by environment variables and REPL/TUI input.
This document is authoritative for script/CI integration boundaries.

Formal invocation grammar (process level):

```text
morphism [UNUSED_ARG...]
morphism-tui [UNUSED_ARG...]
morphism-engine [UNUSED_ARG...]
python -m morphism.cli.shell [UNUSED_ARG...]
python -m morphism.cli.tui [UNUSED_ARG...]
```

Formal REPL command grammar (`morphism`):

```text
<line> ::= <builtin> | <pipeline>
<builtin> ::= "history"
           | "inspect" <ws> <int>
           | "tools"
           | "help" [<ws> <token>]
           | "quit" | "exit" | <EOF>

<pipeline> ::= <linear> | <branch>
<linear> ::= <segment> ( <ws>* "|" <ws>* <segment> )*
<branch> ::= <linear-prefix> <ws>* "|+" <ws>* "(" <segment-list> ")"
<segment-list> ::= <segment> ( <ws>* "," <ws>* <segment> )*
<linear-prefix> ::= <segment> ( <ws>* "|" <ws>* <segment> )*
<segment> ::= <non-empty freeform tokenized string>
```

Tokenization note:

- Parser splits by `|` and branch `|+ (...)` syntax before native command execution.
- Literal pipe characters inside a native command are not escaped at Morphism grammar layer; wrap complex logic in an external script/command stage.

## Global Options

### Command Index Table

| Command | Alias | Type | Stability | Notes |
|---|---|---|---|---|
| `morphism` | `python -m morphism.cli.shell` | interactive REPL | stable | supports built-in shell commands and pipeline expressions |
| `morphism-tui` | `python -m morphism.cli.tui` | interactive TUI | stable | Textual UI entrypoint |
| `morphism-engine` | alias of `morphism-tui` | interactive TUI | stable | same backend behavior as `morphism-tui` |

### Global Options Table

Process-level options/flags:

| Option | Type | Default | Applies To | Behavior | Failure Semantics |
|---|---|---|---|---|---|
| none | n/a | n/a | all commands | No global options parsed by Morphism 3.1.x entrypoints. | Extra argv is ignored by Morphism command parser layer; behavior depends on launcher/runtime shell. |

Runtime controls (environment-backed):

| Control | Type | Default | Override Source | Behavior | Failure Semantics |
|---|---|---|---|---|---|
| `MORPHISM_OLLAMA_URL` | string URL | `http://localhost:11434/api/generate` | env | synthesis endpoint | connection/timeouts can lead to synthesis failure |
| `MORPHISM_MODEL_NAME` | string | `qwen2.5-coder:1.5b` | env | model used by Ollama synthesizer | poor candidate quality increases retries/failures |
| `MORPHISM_Z3_TIMEOUT_MS` | int | `2000` | env | verification solver timeout | `unknown`/timeout may raise verification failure |
| `MORPHISM_LOG_LEVEL` | string | `INFO` | env | console verbosity | invalid values effectively fall back to INFO level mapping |
| `MORPHISM_MAX_SYNTHESIS_ATTEMPTS` | int | `6` | env | candidate retry budget per mismatch | exhaustion raises `VerificationFailedError` |
| `MORPHISM_LLM_REQUEST_TIMEOUT` | int seconds | `60` | env | synthesis HTTP timeout | request timeout and eventual synthesis failure |

Precedence rules (implemented behavior):

1. CLI flag overrides: not implemented.
2. Config file values: not implemented.
3. Environment variables: implemented (`MORPHISM_*`).
4. Built-in defaults: dataclass defaults in `morphism.config`.

Effective precedence in 3.1.x: `environment` -> `built-in defaults`.

## Commands

### `morphism`

Type: interactive REPL.

Invocation:

```bash
morphism
```

Input contract:

- stdin: interactive terminal lines.
- accepted line classes: built-ins or pipeline expressions.

Output contract:

- stdout:
  - success value line: `>>> <result>`
  - handled error line: `[Morphism] ERROR: <message>`
  - unexpected error line: `[Morphism] UNEXPECTED ERROR: <message>`
  - built-in command responses (`history`, `inspect`, `tools`, `quit`)
- stderr:
  - logger stream handler output (environment dependent)

Machine-readable output mode:

- not implemented as dedicated mode.
- use external wrappers or pipeline stages that emit JSON.

Exit semantics:

- process exits on `quit`, `exit`, `EOF`, or external termination.
- handled per-line failures do not terminate process by default.

Minimal example:

```bash
morphism
```

Advanced example (branch):

```text
µ> emit_raw |+ (render_float, render_float)
```

Expected snippet:

```text
>>> [RENDERED UI]: 0.5
```

#### REPL built-ins (`morphism` only)

##### `history`

Syntax:

```text
history
```

Behavior:

- prints current pipeline node list in insertion order.

Output:

```text
(1) emit_raw -> (2) AI_Bridge_Functor -> (3) render_float
```

Failure semantics:

- if no pipeline executed:

```text
[Morphism] No pipeline executed yet.
```

##### `inspect <node_number>`

Syntax:

```text
inspect <int>
```

Argument:

- `node_number`: 1-based integer index into current pipeline `all_nodes`.

Behavior:

- prints node name, schema transition, and last output state.

Failure semantics:

- invalid arg:

```text
[Morphism] Usage: inspect <node number>
```

- out of range:

```text
[Morphism] Node <n> does not exist. Pipeline has <k> node(s).
```

##### `tools`

Syntax:

```text
tools
```

Behavior:

- prints registered built-in tools and schema signatures.

Current registry (3.1.x):

- `emit_raw`
- `render_float`

##### `help`

Syntax:

```text
help
help <command>
```

Behavior:

- provided by `cmd.Cmd` default help framework.

##### `quit`, `exit`, `EOF`

Syntax:

```text
quit
exit
```

Behavior:

- prints goodbye message and terminates REPL loop.

### `morphism-tui`

Type: interactive Textual UI.

Invocation:

```bash
morphism-tui
```

Input contract:

- command text entered via TUI command input widget.
- supports same pipeline grammar as REPL.

Output contract:

- UI telemetry pane receives result and error messages.
- console/log file receives logger output.

Machine-readable output mode:

- not implemented.

Built-in key bindings:

- `Ctrl+C` -> quit
- `Ctrl+Q` -> quit

Execution behavior notes:

- command execution runs in exclusive worker (`@work(exclusive=True)`).
- input is disabled while active execution runs.

Minimal example:

```bash
morphism-tui
```

Advanced example:

- enter `emit_raw | render_float` in command input and submit.

### `morphism-engine`

Type: alias of `morphism-tui`.

Invocation:

```bash
morphism-engine
```

Behavior:

- identical runtime behavior and contracts as `morphism-tui`.

Minimal example:

```bash
morphism-engine
```

Advanced example:

- run branch expression in TUI command box: `emit_raw |+ (render_float, render_float)`.

## Exit Codes

### Process-level exit codes (stock commands)

| Code | Command Class | Meaning |
|---|---|---|
| 0 | REPL/TUI normal termination | process exited normally (`quit`/UI exit) |
| non-zero | launcher/runtime failure | unhandled process error outside normal command-loop handling |

Important:

- command-level pipeline failures inside interactive sessions are handled and reported without deterministic non-zero process exit.
- for CI-grade exit semantics, use non-interactive wrapper scripts that map exceptions to explicit codes.

### Recommended wrapper exit codes (integration contract)

| Code | Meaning | Suggested Trigger |
|---|---|---|
| 0 | success | pipeline completed with expected output |
| 10 | synthesis failure | `SynthesisTimeoutError` / backend unavailable |
| 11 | verification failure | `VerificationFailedError` |
| 12 | configuration error | invalid/missing runtime config/env |
| 13 | runtime execution error | `EngineExecutionError` |
| 14 | usage/grammar error | parser or wrapper validation failure |

## Environment Variables

### ENV Variable Reference

| Variable | Type | Default | Scope | Used By | Notes |
|---|---|---|---|---|---|
| `MORPHISM_OLLAMA_URL` | URL string | `http://localhost:11434/api/generate` | synthesis | `OllamaSynthesizer` | should point to `/api/generate` endpoint |
| `MORPHISM_MODEL_NAME` | string | `qwen2.5-coder:1.5b` | synthesis | `OllamaSynthesizer` | model must exist on Ollama host |
| `MORPHISM_Z3_TIMEOUT_MS` | int | `2000` | verification | `verify_functor_mapping` | millisecond timeout for solver |
| `MORPHISM_LOG_LEVEL` | string | `INFO` | logging | logger setup | affects console verbosity |
| `MORPHISM_MAX_SYNTHESIS_ATTEMPTS` | int | `6` | synthesis orchestration | pipeline mismatch resolver | retries candidate generation loop |
| `MORPHISM_LLM_REQUEST_TIMEOUT` | int seconds | `60` | synthesis transport | `aiohttp` timeout | applies per synthesis request |

Shell export examples:

bash/zsh:

```bash
export MORPHISM_LOG_LEVEL=DEBUG
export MORPHISM_Z3_TIMEOUT_MS=3000
```

fish:

```fish
set -x MORPHISM_LOG_LEVEL DEBUG
set -x MORPHISM_Z3_TIMEOUT_MS 3000
```

PowerShell:

```powershell
$env:MORPHISM_LOG_LEVEL = "DEBUG"
$env:MORPHISM_Z3_TIMEOUT_MS = "3000"
```

## Diagnostics and Errors

### Error Code / Diagnostic Mapping

| Diagnostic Signature | Typical Source | Stock Process Exit | Wrapper Exit | Primary Remediation |
|---|---|---|---|---|
| `[Morphism] ERROR: TYPE MISMATCH ...` | schema mismatch with no repair path | 0 (session continues) | 14 or 11 | provide LLM client path or explicit pinned bridge |
| `Ollama synthesis failed after ... retries` | synthesis backend/network timeout | 0 (if handled in-session) | 10 | validate endpoint/model/timeouts |
| `Functor F(... ) failed verification ...` | candidate rejected or timed out | 0 (if handled in-session) | 11 | adjust transform/schema strategy; inspect constraints |
| `Command '<cmd>' exited with code ...` | native subprocess failure | 0 (if handled in-session) | 13 | fix native command, env, quoting |
| `[Morphism] UNEXPECTED ERROR: ...` | uncaught runtime issue in line execution | 0 (session continues) | 13/14 | inspect traceback in logs |

Failure semantics by command class:

- REPL/TUI: line-level failures are isolated and reported; session remains alive.
- wrapper/API execution: failures should map to explicit non-zero exits for automation.

## Compatibility Notes

### Shell compatibility

bash/zsh:

- JSON payload quoting preferred with single quotes around full JSON string.

```bash
morphism
# in REPL:
echo '{"score":85}' | render_float
```

fish:

- verify pipeline token handling in shell; keep complex logic in `python -c` stage or script file.

PowerShell:

- prefer single-quoted JSON strings when possible.

```powershell
morphism
# in REPL:
echo '{"score":85}' | render_float
```

JSON escaping edge cases:

- nested quotes in one-liners are fragile across shells.
- for deterministic behavior, move payload construction into script files or heredocs.

### Backward compatibility and deprecation tags

| Item | Status | Tag | Notes |
|---|---|---|---|
| `morphism` entrypoint | active | stable | primary REPL path |
| `morphism-tui` entrypoint | active | stable | TUI command |
| `morphism-engine` entrypoint | active | stable alias | equivalent to TUI command |
| process flags (`--dry-run`, `--strict`, etc.) | absent | not-implemented | referenced in docs as wrapper patterns only |
| config file/profile selection | absent | not-implemented | environment-only configuration in 3.1.x |

### Experimental matrix

| Capability | Status | Stability Annotation |
|---|---|---|
| Branch grammar `|+ (...)` | active | stable in 3.1.x |
| Runtime mismatch repair on `Pending` schemas | active | stable behavior, model-dependent outcome |
| Deterministic non-interactive mode | via wrapper only | integration pattern, not native CLI feature |
| Cache bypass/invalidation flags | absent | operational workaround (`.morphism_cache.db` management) |

## Appendix (advanced examples)

### A1. Minimal REPL success path

```bash
morphism
```

```text
µ> emit_raw | render_float
>>> [RENDERED UI]: 0.5
µ> quit
[Morphism] Goodbye.
```

### A2. REPL branch path

```text
µ> emit_raw |+ (render_float, render_float)
>>> [RENDERED UI]: 0.5
```

### A3. REPL diagnostics path

```text
µ> emit_raw | render_float
µ> history
µ> inspect 2
```

Expected snippets:

```text
(1) emit_raw -> (2) AI_Bridge_Functor -> (3) render_float
[Node 2] AI_Bridge_Functor
  Schema : Int_0_to_100 -> Float_Normalized
```

### A4. TUI launch

```bash
morphism-tui
```

Enter in command input:

```text
emit_raw | render_float
```

### A5. Alias launch

```bash
morphism-engine
```

### A6. Non-interactive wrapper with explicit exit map

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
    emit = FunctorNode(Int_0_to_100, Int_0_to_100, lambda x: 50, 'emit_raw')
    render = FunctorNode(Float_Normalized, String_NonEmpty, lambda x: f'[RENDERED UI]: {x}', 'render_float')
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

### A7. Cache cold/warm deterministic replay control

Cold run:

```bash
python -c "from pathlib import Path; Path('.morphism_cache.db').unlink(missing_ok=True)"
```

Warm run verification:

```bash
python -c "import sqlite3; c=sqlite3.connect('.morphism_cache.db'); print(c.execute('select count(*) from functors').fetchone()[0]); c.close()"
```

### A8. PowerShell-safe env and launch

```powershell
$env:MORPHISM_LOG_LEVEL = "DEBUG"
$env:MORPHISM_MAX_SYNTHESIS_ATTEMPTS = "2"
morphism
```
