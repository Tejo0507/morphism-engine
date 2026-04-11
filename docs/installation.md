---
title: Morphism Engine Installation
description: Production-grade installation and verification guide for Morphism Engine across local, CI, container, and restricted enterprise environments.
slug: /installation
---

## Overview

Morphism Engine is distributed as a Python package (`morphism-engine`, current series `3.1.x`) with console entry points:

- `morphism` (classic REPL)
- `morphism-tui` (Textual TUI)
- `morphism-engine` (alias of TUI)

Runtime baseline:

- Python `>=3.11`
- `z3-solver>=4.12` (Python wheel dependency)
- `aiohttp`, `requests`, `textual`
- Optional but operationally important for self-healing bridges: local Ollama endpoint + model (default `qwen2.5-coder:1.5b`)

### Versioning Policy and Compatibility

- Morphism Engine uses semantic versioning for the distributable package (`MAJOR.MINOR.PATCH`).
- CLI compatibility contract:
    - `PATCH`: no intentional CLI command surface break.
    - `MINOR`: additive CLI behavior/commands may be introduced; existing commands should remain functional.
    - `MAJOR`: breaking changes may occur and require migration review.
- Current command entry points in `3.1.x`:
    - `morphism`
    - `morphism-tui`
    - `morphism-engine`
- Schema and migration behavior (implementation-aware):
    - Runtime schemas are code-defined objects, not externally versioned schema files.
    - Bridge cache is persisted in local SQLite (`.morphism_cache.db`) and is safe to delete.
    - For upgrades/downgrades across minor/major versions, clear cache to prevent reuse of stale synthesized bridges.
- Backward compatibility guidance:
    - Pin an exact version in CI/production (`morphism-engine==3.1.0`).
    - Treat unpinned installs as non-deterministic across time.

### Dependency Model

- Required runtime:
    - Python `>=3.11`
    - Python package dependencies from `pyproject.toml`:
        - `z3-solver>=4.12`
        - `aiohttp>=3.9`
        - `requests>=2.31`
        - `textual>=0.50`
- Solver dependency details:
    - Morphism imports Z3 through `z3-solver` Python wheels (`import z3`).
    - No standalone system `z3` binary is required for normal operation.
- Optional accelerators and external services:
    - Ollama service for bridge synthesis (`MORPHISM_OLLAMA_URL`, default `http://localhost:11434/api/generate`).
    - Model selection via `MORPHISM_MODEL_NAME` (default `qwen2.5-coder:1.5b`).
    - GPU acceleration is handled by Ollama runtime/hardware configuration, not by Morphism directly.
- Useful runtime controls:
    - `MORPHISM_Z3_TIMEOUT_MS`
    - `MORPHISM_LLM_REQUEST_TIMEOUT`
    - `MORPHISM_MAX_SYNTHESIS_ATTEMPTS`
    - `MORPHISM_LOG_LEVEL`

### Platform Matrix

| Environment | Support Level | Recommended Channel | Notes |
|---|---|---|---|
| macOS (Intel/Apple Silicon) | Supported | `pipx` or `venv + pip` | Use Python 3.11+ from Homebrew/pyenv/company image. |
| Linux (x86_64/arm64) | Supported | `venv + pip` | Preferred for servers and CI. |
| Windows (native) | Supported | `py -3.11 -m venv` + `pip` | Use PowerShell examples below. |
| Windows + WSL2 | Supported | Linux path in WSL | Keep project and cache inside WSL filesystem for best performance. |
| Containers | Supported | Build image from pinned wheel(s) | No requirement for root runtime user. |
| CI runners (GitHub/GitLab/Jenkins/Azure) | Supported | pinned `pip` install + smoke test | Use deterministic lock/constraints and optional artifact mirror. |

### Fast Path

Use this when you need a reliable developer setup quickly.

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install morphism-engine==3.1.0
python -c "from importlib.metadata import version; print(version('morphism-engine'))"
python -c "import z3; print('Z3_OK', z3.get_version_string())"
```

Expected Output:

```text
3.1.0
Z3_OK <z3-version>
```

### Deep Setup Path

Use this for enterprise, CI/CD, deterministic builds, and locked-down hosts.

1. Pin Python interpreter version (for example `3.11.9`).
2. Install from a vetted artifact source (internal mirror or verified release asset).
3. Enforce hash checking for package installs.
4. Verify runtime + solver + optional Ollama endpoint.
5. Run deterministic smoke tests.
6. Archive install metadata (`pip freeze`, wheel checksums, build logs).

## Recommended Install Paths

1. Package manager (recommended for most users):
- `pipx` for isolated CLI installs on engineer workstations.
- `pip` in virtual environments for services, CI, and containers.

2. Direct artifact install (release wheel/sdist):
- Install from a local `.whl` file or pre-downloaded artifact.
- Best for controlled change management and restricted networks.

3. Source build (for contributors and custom patching):
- Editable install from repo (`pip install -e .` or `pip install -e ".[dev]"`).

4. Offline/air-gapped:
- Pre-build a wheelhouse externally.
- Transfer wheels + hashes into restricted network.
- Install with `--no-index --find-links`.

## OS-Specific Installation

### macOS

#### A) `pipx` (workstation CLI isolation)

```bash
brew install python@3.11 pipx
pipx ensurepath
pipx install "morphism-engine==3.1.0"
```

Verify:

```bash
morphism --help
python3 -c "from importlib.metadata import version; print(version('morphism-engine'))"
```

Expected Output:

```text
(Interactive Morphism shell banner/help)
3.1.0
```

#### B) `venv + pip` (service-compatible)

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install "morphism-engine==3.1.0"
```

#### C) Direct wheel install

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install /path/to/morphism_engine-3.1.0-py3-none-any.whl
```

### Linux

#### A) `venv + pip` (recommended)

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install "morphism-engine==3.1.0"
```

#### B) Source build

```bash
git clone <your-fork-or-mirror-url>
cd morphism-engine
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

#### C) Offline/air-gapped install

Online staging host:

```bash
mkdir -p wheelhouse
pip download --dest wheelhouse "morphism-engine==3.1.0"
pip download --dest wheelhouse "z3-solver>=4.12" "aiohttp>=3.9" "requests>=2.31" "textual>=0.50"
( cd wheelhouse && sha256sum * > SHA256SUMS )
```

Air-gapped host:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --no-index --find-links ./wheelhouse morphism-engine==3.1.0
sha256sum -c wheelhouse/SHA256SUMS
```

### Windows Native (PowerShell)

#### A) `venv + pip`

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install "morphism-engine==3.1.0"
```

#### B) Direct wheel install

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install C:\artifacts\morphism_engine-3.1.0-py3-none-any.whl
```

#### C) Offline install from wheelhouse

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --no-index --find-links C:\wheelhouse morphism-engine==3.1.0
Get-FileHash C:\wheelhouse\* -Algorithm SHA256
```

### Windows WSL2

Inside WSL distribution:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install "morphism-engine==3.1.0"
```

Operational note:

- Keep working directory in WSL filesystem (for example `/home/<user>/...`) rather than `/mnt/c/...` to avoid IO and file-lock edge cases.

### Container Images

No root runtime is required. Use pinned dependency install in build stage.

```Dockerfile
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd -m -u 10001 morphism
WORKDIR /app

COPY wheelhouse /wheelhouse
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install --no-index --find-links /wheelhouse morphism-engine==3.1.0

ENV PATH="/opt/venv/bin:${PATH}"
USER morphism

ENTRYPOINT ["morphism"]
```

## Verification

Run verification after every install, image build, or CI environment bootstrap.

### 0) Health Check (configuration + import surface)

```bash
python -c "from morphism.config import config; import morphism.cli.shell,morphism.cli.tui,morphism.math.z3_verifier; print('HEALTH_OK', config.model_name, config.ollama_url)"
```

Expected Output:

```text
HEALTH_OK qwen2.5-coder:1.5b http://localhost:11434/api/generate
```

Fail example:

```text
ModuleNotFoundError: No module named 'morphism'
```

### 1) CLI + Package Version Check

```bash
python -c "from importlib.metadata import version; print(version('morphism-engine'))"
```

Expected Output:

```text
3.1.0
```

Fail example:

```text
importlib.metadata.PackageNotFoundError: morphism-engine
```

### 2) Dependency Checks

```bash
python -c "import z3; print('Z3_OK', z3.get_version_string())"
python -c "import textual,aiohttp,requests; print('PY_DEPS_OK')"
```

Expected Output:

```text
Z3_OK <version>
PY_DEPS_OK
```

Fail example:

```text
ModuleNotFoundError: No module named 'z3'
```

### 3) Optional Ollama Reachability Check (for self-healing mode)

```bash
python -c "import os,requests; url=os.getenv('MORPHISM_OLLAMA_URL','http://localhost:11434/api/generate').replace('/api/generate',''); print('OLLAMA_UP' if requests.get(url,timeout=2).ok else 'OLLAMA_DOWN')"
```

Expected Output:

```text
OLLAMA_UP
```

Fail example:

```text
requests.exceptions.ConnectionError: ...
```

### 4) Functional Smoke Test

Core smoke (no LLM bridge required):

```bash
python -c "from morphism.cli.shell import MorphismShell; import io,sys; s=MorphismShell(); b=io.StringIO(); o=sys.stdout; sys.stdout=b; s.onecmd('emit_raw'); sys.stdout=o; print('SMOKE_PASS' if '>>> 50' in b.getvalue() else 'SMOKE_FAIL'); print(b.getvalue().strip())"
```

Expected Output:

```text
SMOKE_PASS
>>> 50
```

Self-healing smoke (requires Ollama + model):

```bash
python -c "from morphism.cli.shell import MorphismShell; import io,sys; s=MorphismShell(); b=io.StringIO(); o=sys.stdout; sys.stdout=b; s.onecmd('emit_raw | render_float'); sys.stdout=o; print('SMOKE_PASS' if '[RENDERED UI]: 0.5' in b.getvalue() else 'SMOKE_FAIL'); print(b.getvalue().strip())"
```

Expected Output:

```text
SMOKE_PASS
>>> [RENDERED UI]: 0.5
```

Fail example:

```text
SMOKE_FAIL
[Morphism] ERROR: ...
```

## Enterprise/CI Install

### Proxy + Certificate Scenarios

Set standard proxy variables for package downloads and runtime HTTP clients:

```bash
export HTTPS_PROXY=http://proxy.corp:8080
export HTTP_PROXY=http://proxy.corp:8080
export NO_PROXY=localhost,127.0.0.1
```

For corporate CAs:

```bash
export SSL_CERT_FILE=/etc/ssl/certs/corp-ca.pem
export REQUESTS_CA_BUNDLE=/etc/ssl/certs/corp-ca.pem
```

Windows PowerShell:

```powershell
$env:HTTPS_PROXY="http://proxy.corp:8080"
$env:HTTP_PROXY="http://proxy.corp:8080"
$env:NO_PROXY="localhost,127.0.0.1"
$env:SSL_CERT_FILE="C:\certs\corp-ca.pem"
$env:REQUESTS_CA_BUNDLE="C:\certs\corp-ca.pem"
```

### Internal Artifact Mirrors

Pin package source to your internal index:

```bash
pip install --index-url https://pypi.corp.example/simple --trusted-host pypi.corp.example morphism-engine==3.1.0
```

Or use pip configuration (`pip.conf`/`pip.ini`) managed by platform engineering.

### Restricted-Network Install

- Pre-stage wheelhouse and checksum manifest externally.
- Move into restricted segment through approved artifact channel.
- Install with `--no-index --find-links` only.
- Run full verification section post-install.

### Reproducible Install Pinning

Recommended:

1. Pin top-level package version (`morphism-engine==3.1.0`).
2. Pin transitive dependencies in constraints/lock file.
3. Enforce hash-checked installs:

```bash
pip install --require-hashes -r requirements.lock
```

CI note:

- Store lock file + checksums in source control and update only through reviewed dependency bump PRs.

### CI/CD Ops Notes

- Use `morphism` shell smoke tests for headless pipelines; avoid TUI in non-interactive runners.
- Cache wheelhouse or pip cache by Python version and lock-file hash.
- Archive `pip freeze` and verification outputs as build artifacts.
- If self-healing behavior is required in CI, bring up Ollama sidecar/service before running bridge tests.

## Security + Integrity

### Checksum Verification

Linux/macOS:

```bash
sha256sum morphism_engine-3.1.0-py3-none-any.whl
sha256sum -c SHA256SUMS
```

Windows:

```powershell
Get-FileHash .\morphism_engine-3.1.0-py3-none-any.whl -Algorithm SHA256
```

### Signature / Supply-Chain Trust Recommendations

- Prefer artifacts produced by your own trusted CI and stored in an internal registry.
- Require immutable artifact versions and checksum attestation.
- Run dependency scans on wheelhouse before promotion.
- Treat LLM model artifacts (Ollama model pulls) as third-party supply chain and mirror approved model digests internally.

### Least Privilege and Non-Root Guidance

- Do not install Morphism globally into system Python.
- Use `venv` or `pipx` under non-admin user.
- In containers, install in build stage and run as unprivileged user (`USER morphism`).

## Rollback/Uninstall

### Clean Removal

`pip` environment:

```bash
pip uninstall -y morphism-engine
```

`pipx` environment:

```bash
pipx uninstall morphism-engine
```

### Cache/Data Directory Behavior

Current implementation uses local SQLite cache in current working directory:

- `.morphism_cache.db`

Safe removal:

```bash
rm -f .morphism_cache.db
```

Windows:

```powershell
Remove-Item .morphism_cache.db -Force -ErrorAction SilentlyContinue
```

Operational note:

- Cache contains synthesized bridge lambdas keyed by schema pairs.
- Deleting cache is safe and forces re-synthesis/re-verification on next mismatch.

### Downgrade/Revert Procedure

1. Uninstall current version.
2. Install pinned older version.
3. Clear `.morphism_cache.db` to avoid reusing bridge logic generated under a different release.

```bash
pip uninstall -y morphism-engine
pip install morphism-engine==3.0.0
rm -f .morphism_cache.db
```

## Troubleshooting

### Command Not Found

Symptoms:

- `morphism: command not found`
- `morphism is not recognized as an internal or external command`

Diagnostics:

```bash
python -c "import sys; print(sys.executable)"
python -m pip show morphism-engine
```

Actions:

- Activate the intended virtual environment.
- Use module execution if PATH is constrained:

```bash
python -m morphism.cli.shell
```

### Incompatible Dependencies

Symptoms:

- install resolver failures
- import-time `ModuleNotFoundError`

Diagnostics:

```bash
python --version
pip check
python -c "import z3,textual,aiohttp,requests; print('OK')"
```

Actions:

- Use Python `>=3.11`.
- Recreate clean venv and reinstall from pinned requirements.

### Solver Not Detected

Symptoms:

- `No module named 'z3'`

Diagnostics:

```bash
python -c "import z3; print(z3.get_version_string())"
```

Actions:

```bash
pip install --upgrade z3-solver
```

### PATH Collisions

Symptoms:

- Wrong `morphism` executable runs
- global Python shadows project venv

Diagnostics:

Linux/macOS:

```bash
which morphism
python -c "import sys; print(sys.executable)"
```

Windows:

```powershell
Get-Command morphism
python -c "import sys; print(sys.executable)"
```

Actions:

- Invoke binaries from active venv explicitly.
- Remove stale global installs if needed.

### Permissions Issues

Symptoms:

- `Permission denied`
- write errors in protected directories

Actions:

- Install in user-owned `venv`/`pipx` location.
- Avoid system site-packages and root-owned working directories.
- Ensure write permission in working directory for `.morphism_cache.db`.

## Next Steps

- Quick Start: [README Quick Start](../README.md#quick-start)
- CLI Usage: [CLI Shell implementation and command surface](../src/morphism/cli/shell.py)
