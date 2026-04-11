<p align="center">
  <strong>Morphism Engine</strong><br>
  <em>A self-healing, formally verified Category Theory shell.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/tests-73%20passed-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
  <img src="https://img.shields.io/badge/prover-Z3%20SMT-purple" alt="Z3 SMT">
  <img src="https://img.shields.io/badge/LLM-Ollama-orange" alt="Ollama">
  <img src="https://img.shields.io/badge/TUI-Textual-cyan" alt="Textual">
</p>

---

## The Problem

POSIX pipes (`|`) are **untyped**. When you write:

```bash
cat users.json | tr ',' '\n' | wc -l
```

Nothing guarantees the output of `tr` is valid input for `wc -l` in any meaningful sense. One malformed byte and the entire pipeline fails silently — or worse, produces wrong results. There are no schemas, no contracts, and no safety nets.

## The Solution

**Morphism Engine** replaces "hope-based piping" with **mathematically guaranteed type safety**.

Every node in a Morphism pipeline carries a **typed schema** (e.g., `Int_0_to_100`, `Float_Normalized`, `JSON_Object`). When two adjacent nodes disagree on types, the engine:

1. **Detects** the mismatch at link-time.
2. **Synthesises** a bridge functor using a local **Ollama** LLM.
3. **Proves** the bridge is safe via the **Z3 SMT theorem prover** — if Z3 can't prove it, the bridge is rejected. No exceptions.
4. **Caches** the proven functor in a zero-latency **SQLite store** so it's never re-synthesised.
5. **Executes** the repaired pipeline end-to-end.

The result: a shell where **every pipe connection is a formally verified morphism** in the category-theoretic sense.

---

## Features

| Feature | Description |
|---|---|
| **Self-Healing Pipelines** | Schema mismatches are autonomously repaired by AI synthesis + Z3 proof. |
| **Dynamic Schema Inference** | Native subprocesses (`echo`, `curl`, `python -c`) get their output schema inferred at runtime — JSON, CSV, or plaintext. |
| **Zero-Latency Functor Cache** | SQLite WAL-mode cache with SHA-256 keying. A proven bridge is never synthesised twice. |
| **DAG Branching (`\|+`)** | Fan-out a single node to multiple children with `emit_raw \|+ (render_float, to_sql)`. Parallel execution via `asyncio.gather`. |
| **Reactive Textual TUI** | 3-column layout: searchable Tool Catalog, live DAG Topographer tree, node Inspector, and streaming Telemetry log. |
| **Intelligent Autocomplete** | Pipe-aware command suggestions that reset after every `\|` token. |
| **Non-Blocking Execution** | Pipeline runs inside a Textual `@work` worker — the UI never freezes, even during long Ollama calls. |

---

## Installation

### 1. Clone & install

```bash
git clone https://github.com/your-org/morphism-engine.git
cd morphism-engine
pip install -e ".[dev]"
```

This installs three console commands:

| Command | Interface |
|---|---|
| `morphism-engine` | Textual TUI (recommended) |
| `morphism-tui` | Textual TUI (alias) |
| `morphism` | Classic `cmd.Cmd` REPL |

### 2. Pull the Ollama model

The self-healing synthesiser requires a local LLM. Install [Ollama](https://ollama.com), then:

```bash
ollama pull qwen2.5-coder:1.5b
```

### 3. Verify

```bash
pytest tests/ -v
```

All **73 tests** should pass.

---

## Quick Start

### Launch the TUI

```bash
morphism-engine
```

### Run a linear pipeline

Type in the command bar:

```
emit_raw | render_float
```

`emit_raw` outputs an `Int_0_to_100` value. `render_float` expects `Float_Normalized`. The engine detects the mismatch, synthesises a bridge (`x / 100.0`), proves it with Z3, and executes the full chain.

### Fan-out with DAG branching

```
emit_raw |+ (render_float, render_float)
```

The output of `emit_raw` fans out to two parallel `render_float` nodes, executed concurrently.

### Run native subprocesses

```
echo {"name":"Ada"} | python -c "import sys,json; print(json.load(sys.stdin)['name'])"
```

Morphism infers `JSON_Object` for the first node and `Plaintext` for the second, auto-bridging as needed.

---

## Architecture

```
                        Morphism Engine — Under the Hood
  ┌─────────────────────────────────────────────────────────────────────┐
  │                                                                     │
  │   User Input                                                        │
  │       │                                                             │
  │       ▼                                                             │
  │   ┌─────────┐     ┌──────────────┐     ┌─────────────┐             │
  │   │  Parse  │────▶│  Link Nodes  │────▶│  Schema     │             │
  │   │  (| |+) │     │  (DAG build) │     │  Check      │             │
  │   └─────────┘     └──────────────┘     └──────┬──────┘             │
  │                                               │                     │
  │                              ┌────────────────┼────────────────┐    │
  │                              │  Match?        │  Mismatch?     │    │
  │                              ▼                ▼                │    │
  │                         ┌─────────┐    ┌─────────────┐        │    │
  │                         │  Exec   │    │ Cache Check  │        │    │
  │                         │  as-is  │    │ (SQLite)     │        │    │
  │                         └─────────┘    └──────┬──────┘        │    │
  │                                               │                │    │
  │                                   ┌───────────┼──────────┐     │    │
  │                                   │ HIT       │ MISS     │     │    │
  │                                   ▼           ▼          │     │    │
  │                             ┌──────────┐ ┌──────────┐    │     │    │
  │                             │ Load     │ │ AI Synth │    │     │    │
  │                             │ Cached   │ │ (Ollama) │    │     │    │
  │                             │ Functor  │ └────┬─────┘    │     │    │
  │                             └────┬─────┘      │          │     │    │
  │                                  │            ▼          │     │    │
  │                                  │      ┌──────────┐     │     │    │
  │                                  │      │ Z3 Proof │     │     │    │
  │                                  │      │ (SMT)    │     │     │    │
  │                                  │      └────┬─────┘     │     │    │
  │                                  │           │           │     │    │
  │                                  │    ┌──────┴──────┐    │     │    │
  │                                  │    │PASS?  FAIL? │    │     │    │
  │                                  │    ▼       ▼     │    │     │    │
  │                                  │  Cache   Retry/  │    │     │    │
  │                                  │  Store   Reject  │    │     │    │
  │                                  │    │             │    │     │    │
  │                                  ▼    ▼             │    │     │    │
  │                            ┌──────────────┐         │    │     │    │
  │                            │  JIT Execute │         │    │     │    │
  │                            │  (pipeline)  │         │    │     │    │
  │                            └──────┬───────┘         │    │     │    │
  │                                   │                 │    │     │    │
  │                                   ▼                 │    │     │    │
  │                              ┌──────────┐           │    │     │    │
  │                              │  Output  │           │    │     │    │
  │                              └──────────┘           │    │     │    │
  │                                                     │    │     │    │
  │                              ───────────────────────┘────┘─────┘    │
  └─────────────────────────────────────────────────────────────────────┘
```

### Key modules

| Module | Purpose |
|---|---|
| `morphism.core.pipeline` | Async DAG executor with `asyncio.gather` fan-out |
| `morphism.core.node` | `FunctorNode` — DAG vertex with typed schemas |
| `morphism.core.schemas` | `Schema` dataclass + built-in instances |
| `morphism.core.cache` | `FunctorCache` — SQLite WAL + SHA-256 keying |
| `morphism.core.native_node` | `NativeCommandNode` — OS subprocess wrapper |
| `morphism.core.inference` | Runtime schema inference (JSON / CSV / Plaintext) |
| `morphism.ai.synthesizer` | Ollama LLM client for bridge functor generation |
| `morphism.math.z3_verifier` | Z3 SMT proof of generated functors |
| `morphism.cli.tui` | Textual TUI (recommended interface) |
| `morphism.cli.shell` | Classic `cmd.Cmd` REPL (fallback) |

---

## Testing

```bash
# Run the full suite
pytest tests/ -v

# Run only TUI tests
pytest tests/test_phase11_tui.py -v

# Run only cache + DAG tests
pytest tests/test_phase9_10.py -v
```

**73 tests** across 8 test files covering schema verification, self-healing synthesis, native subprocess integration, SQLite cache lifecycle, DAG branching, and headless TUI pilot tests.

---

## Requirements

| Dependency | Version | Purpose |
|---|---|---|
| Python | ≥ 3.11 | Runtime |
| z3-solver | ≥ 4.12 | Formal verification of bridge functors |
| aiohttp | ≥ 3.9 | Async HTTP client for Ollama |
| requests | ≥ 2.31 | Sync HTTP fallback |
| textual | ≥ 0.50 | Reactive terminal UI framework |
| Ollama | latest | Local LLM inference server |

---

## License

MIT
