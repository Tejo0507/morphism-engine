---
title: Morphism Engine Configuration Reference
slug: /configuration-reference
description: Authoritative configuration specification for Morphism Engine covering runtime environment settings, canonical file schema, profiles, security controls, and migration guidance.
---

## Configuration Overview

This reference separates configuration into two explicit layers:

1. Native runtime configuration (implemented in Morphism 3.1.x).
2. Canonical file schema (spec for platform wrappers/tooling; not auto-loaded by core runtime in 3.1.x).

Key fact for operators:

- Core runtime currently reads environment variables only (`MORPHISM_*`) plus built-in defaults.
- No built-in config file parser or profile switch is implemented in 3.1.x.
- File-based configuration in this document is authoritative as an integration spec for wrappers and future native support.

## Source Precedence

### Implemented precedence (core runtime 3.1.x)

1. Environment variables (`MORPHISM_*`)
2. Built-in defaults in `morphism.config.MorphismConfig`

### Canonical precedence model (wrapper/future-native spec)

1. CLI flags (not implemented in core 3.1.x)
2. Project config file (not implemented in core 3.1.x)
3. User/global config file (not implemented in core 3.1.x)
4. Environment variables
5. Built-in defaults

### Precedence resolution matrix

| Source | Core 3.1.x | Wrapper Spec | Notes |
|---|---|---|---|
| CLI flags | not supported | highest | wrapper may expose and map to env/runtime |
| Project file (`./morphism.toml`) | ignored by core | high | repository-scoped policy |
| User file (`~/.config/morphism/config.toml`) | ignored by core | medium | developer defaults |
| Environment (`MORPHISM_*`) | active | medium-low | process-level override in core |
| Built-in defaults | active | lowest | fallback only |

## Schema Reference

### A) Native runtime schema (implemented)

Full schema table:

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `MORPHISM_OLLAMA_URL` | string (URL) | `http://localhost:11434/api/generate` | no | Synthesis endpoint for Ollama-backed transform generation. |
| `MORPHISM_MODEL_NAME` | string | `qwen2.5-coder:1.5b` | no | Model name passed to synthesis backend. |
| `MORPHISM_Z3_TIMEOUT_MS` | integer | `2000` | no | Z3 solver timeout per verification attempt in milliseconds. |
| `MORPHISM_LOG_LEVEL` | string | `INFO` | no | Console log level. |
| `MORPHISM_MAX_SYNTHESIS_ATTEMPTS` | integer | `6` | no | Max candidate retries for mismatch repair. |
| `MORPHISM_LLM_REQUEST_TIMEOUT` | integer (seconds) | `60` | no | HTTP timeout for synthesis request. |

Validation rules (implemented/implicit):

- Integer fields must parse as base-10 integers; invalid values raise at config construction.
- `MORPHISM_LOG_LEVEL` is interpreted via Python logging lookup; unknown values effectively behave like INFO.
- URL/model validity is not prevalidated; errors surface at synthesis request time.

Allowed ranges (operationally recommended):

- `MORPHISM_Z3_TIMEOUT_MS`: 100 to 60000
- `MORPHISM_MAX_SYNTHESIS_ATTEMPTS`: 1 to 20
- `MORPHISM_LLM_REQUEST_TIMEOUT`: 5 to 300

### B) Canonical config file schema v1 (integration spec)

Status:

- Not auto-loaded by core runtime in 3.1.x.
- Intended for wrapper/tooling loaders and future native file support.

File name/location conventions:

- Project: `./morphism.toml`
- User/global: `~/.config/morphism/config.toml` (Windows equivalent under `%APPDATA%`)

Top-level schema keys:

- `schema_version`
- `profile`
- `runtime`
- `synthesis`
- `verification`
- `cache`
- `observability`
- `security`
- `policy`

Full schema table:

| Key | Type | Default | Required | Description |
|---|---|---|---|---|
| `schema_version` | integer | `1` | yes | Config schema major version for compatibility checks. |
| `profile` | string enum | `dev` | no | Active profile label (`dev`, `ci`, `prod`, `enterprise`). |
| `runtime.non_interactive` | boolean | `false` | no | Disallow prompts/interactive fallbacks in wrappers. |
| `runtime.strict_mode` | boolean | `false` | no | Fail on policy violations and unresolved ambiguities. |
| `runtime.verification_required` | boolean | `true` | no | Require transform verification before execution admission. |
| `runtime.dry_run` | boolean | `false` | no | Plan and validate only; skip node execution. |
| `runtime.max_pipeline_seconds` | integer | `0` | no | Global pipeline timeout; `0` means disabled. |
| `synthesis.backend` | string enum | `ollama` | no | `ollama`, `mock`, or `disabled`. |
| `synthesis.model` | string | `qwen2.5-coder:1.5b` | no | Model identifier for backend routing. |
| `synthesis.endpoint` | string URL | `http://localhost:11434/api/generate` | no | Synthesis endpoint URL. |
| `synthesis.request_timeout_s` | integer | `60` | no | Per-request timeout seconds. |
| `synthesis.max_attempts` | integer | `6` | no | Candidate retry budget. |
| `synthesis.cost_ceiling_tokens` | integer | `0` | no | Optional wrapper-enforced token ceiling; `0` disabled. |
| `verification.enabled` | boolean | `true` | no | Enable verifier path for generated transforms. |
| `verification.z3_timeout_ms` | integer | `2000` | no | Solver timeout in ms. |
| `verification.constraint_level` | string enum | `standard` | no | `standard` or `strict` constraint policy in wrappers. |
| `verification.reject_unknown` | boolean | `true` | no | Fail on solver `unknown` result. |
| `cache.backend` | string enum | `sqlite` | no | Cache backend (`sqlite` in core). |
| `cache.path` | string path | `.morphism_cache.db` | no | Cache file path. |
| `cache.read_enabled` | boolean | `true` | no | Allow cache reads before synthesis. |
| `cache.write_enabled` | boolean | `true` | no | Persist accepted transforms. |
| `cache.invalidate_on_model_change` | boolean | `false` | no | Wrapper-level invalidation policy on model changes. |
| `cache.max_entries` | integer | `0` | no | Optional wrapper-enforced size cap; `0` disabled. |
| `observability.log_level` | string enum | `INFO` | no | Console log verbosity. |
| `observability.log_file` | string path | `logs/morphism.log` | no | File sink path. |
| `observability.log_format` | string enum | `text` | no | `text` or `json` (json via wrapper formatter). |
| `observability.redact_fields` | array[string] | `[]` | no | Field names to redact in wrapper logs/artifacts. |
| `observability.proof_artifact_dir` | string path | `` | no | Optional directory for persisted proof metadata. |
| `observability.retain_days` | integer | `0` | no | Artifact retention; `0` uses external retention policy. |
| `security.ca_bundle` | string path | `` | no | TLS trust bundle path for HTTP clients. |
| `security.no_proxy` | array[string] | `[]` | no | Hosts excluded from proxying. |
| `security.require_allowlisted_schema_pairs` | boolean | `false` | no | Enforce policy allowlist for synthesis boundaries. |
| `security.allowlisted_schema_pairs` | array[string] | `[]` | no | Entries like `Int_0_to_100->Float_Normalized`. |
| `security.disable_generated_code` | boolean | `false` | no | Block generated transform execution unless pinned transforms used. |
| `security.secret_sources` | array[string] | `[]` | no | Accepted secret providers (`env`, `vault`, `file`) for wrappers. |
| `policy.fail_on_unpinned_critical_boundaries` | boolean | `false` | no | Enforce explicit transforms on marked boundaries. |
| `policy.critical_boundaries` | array[string] | `[]` | no | Schema pair list treated as critical. |

Validation rules (canonical schema):

- `schema_version` must be integer >= 1.
- `profile` must be one of `dev`, `ci`, `prod`, `enterprise`.
- `synthesis.max_attempts` must be >= 1.
- `verification.z3_timeout_ms` must be >= 1.
- `cache.backend` currently supports `sqlite` only for core-compatible operation.
- `security.allowlisted_schema_pairs` entries must match `<SchemaA>-><SchemaB>` format.

Invalid examples:

- `synthesis.max_attempts = 0` (invalid range)
- `verification.z3_timeout_ms = -5` (invalid range)
- `profile = "staging"` (unsupported enum)
- `cache.backend = "redis"` with core runtime only (unsupported backend)

## Profiles

Profiles are wrapper-level overlays in 3.1.x (core does not load profile files natively).

### local/dev profile

Goals:

- fast iteration
- verbose diagnostics
- permissive retries

Recommended:

- `observability.log_level = "DEBUG"`
- `synthesis.max_attempts = 6`
- `runtime.strict_mode = false`

### CI profile

Goals:

- deterministic behavior
- bounded runtime
- fail fast

Recommended:

- `runtime.non_interactive = true`
- `runtime.strict_mode = true`
- `synthesis.max_attempts = 1..2`
- `verification.reject_unknown = true`

### production profile

Goals:

- stable boundaries
- limited nondeterminism
- auditable operation

Recommended:

- `runtime.strict_mode = true`
- `policy.fail_on_unpinned_critical_boundaries = true`
- `cache.read_enabled = true`, `cache.write_enabled = true`
- lower synthesis attempt budget than dev

### enterprise/private-infra profile

Goals:

- policy enforcement
- controlled egress
- secret hygiene

Recommended:

- `security.require_allowlisted_schema_pairs = true`
- explicit `security.ca_bundle`
- managed `security.secret_sources`
- `observability.redact_fields` populated

## Security and Secrets

Secrets handling model:

- Core 3.1.x reads plain environment variables; no native secret manager integration.
- Use external secret injection systems (CI secret store, vault agent, platform env injection).

Credential source strategy (recommended wrapper policy):

1. secret manager (vault/KMS)
2. short-lived environment injection
3. encrypted file mounts (last resort)

Policy enforcement switches (canonical schema):

- `security.require_allowlisted_schema_pairs`
- `security.disable_generated_code`
- `policy.fail_on_unpinned_critical_boundaries`

Network/certificate controls:

- Configure `security.ca_bundle` and process-level TLS env vars as needed.
- Restrict synthesis endpoint egress to approved hosts.

Secure configuration checklist:

1. Set explicit synthesis endpoint/model; do not rely on implicit defaults in production.
2. Enforce strict mode and non-interactive mode in CI/prod wrappers.
3. Define and enforce critical boundary allowlists.
4. Redact sensitive fields in logs and artifacts.
5. Pin or disable generated transforms on regulated boundaries.
6. Set bounded timeouts and retry budgets.
7. Store config files outside world-readable locations.
8. Version control non-secret config; never commit credentials.

## Observability

Implemented in core 3.1.x:

- Console logs via configured log level.
- File logs at `logs/morphism.log` with timestamp + logger namespace.
- Cache artifact at `.morphism_cache.db`.

Canonical observability controls (wrapper/future-native):

- `observability.log_format` (`text`/`json`)
- `observability.redact_fields`
- `observability.proof_artifact_dir`
- `observability.retain_days`

Trace/proof artifact retention:

- Core does not persist standalone proof transcripts currently.
- Use wrapper instrumentation to record verification metadata and retention lifecycle.

## Migration and Compatibility

Schema versioning strategy:

- `schema_version` in config file defines major schema contract.
- Breaking changes increment major version and require explicit migration.

Forward/backward compatibility policy:

- Unknown keys: wrappers should reject in strict mode, warn-and-ignore in dev mode.
- Missing optional keys: defaulted.
- Deprecated keys: accept with warning during one major cycle.

Upgrade warning and migration path:

1. Validate config with target schema version.
2. Apply deterministic migration transform (vN -> vN+1).
3. Re-run config lint and representative pipeline smoke tests.
4. Roll forward with canary profile before full rollout.

Recommended migration warnings:

- old key mapped to new key
- enum value deprecated
- unsupported backend in current runtime

## Examples

### Minimal config file (canonical schema)

```toml
schema_version = 1
profile = "dev"

[synthesis]
backend = "ollama"
model = "qwen2.5-coder:1.5b"
endpoint = "http://localhost:11434/api/generate"
```

### Standard config file

```toml
schema_version = 1
profile = "prod"

[runtime]
non_interactive = true
strict_mode = true
verification_required = true

[synthesis]
backend = "ollama"
model = "qwen2.5-coder:1.5b"
endpoint = "http://localhost:11434/api/generate"
request_timeout_s = 45
max_attempts = 3

[verification]
enabled = true
z3_timeout_ms = 2500
reject_unknown = true

[cache]
backend = "sqlite"
path = ".morphism_cache.db"
read_enabled = true
write_enabled = true

[observability]
log_level = "INFO"
log_file = "logs/morphism.log"
```

### Strict enterprise config file

```toml
schema_version = 1
profile = "enterprise"

[runtime]
non_interactive = true
strict_mode = true
verification_required = true

[synthesis]
backend = "ollama"
model = "qwen2.5-coder:1.5b"
endpoint = "https://ollama.internal.example/api/generate"
request_timeout_s = 30
max_attempts = 2

[verification]
enabled = true
z3_timeout_ms = 2000
constraint_level = "strict"
reject_unknown = true

[cache]
backend = "sqlite"
path = "/var/lib/morphism/cache/morphism_cache.db"
read_enabled = true
write_enabled = true
invalidate_on_model_change = true

[security]
ca_bundle = "/etc/pki/internal-ca.pem"
require_allowlisted_schema_pairs = true
allowlisted_schema_pairs = [
  "Int_0_to_100->Float_Normalized"
]
disable_generated_code = false
secret_sources = ["vault", "env"]

[policy]
fail_on_unpinned_critical_boundaries = true
critical_boundaries = [
  "JSON_Object->Float_Normalized"
]

[observability]
log_level = "INFO"
log_file = "/var/log/morphism/morphism.log"
log_format = "json"
redact_fields = ["token", "password", "api_key"]
retain_days = 30
```

### CI non-interactive config file

```toml
schema_version = 1
profile = "ci"

[runtime]
non_interactive = true
strict_mode = true
verification_required = true
max_pipeline_seconds = 120

[synthesis]
backend = "mock"
request_timeout_s = 10
max_attempts = 1

[verification]
enabled = true
z3_timeout_ms = 1500
reject_unknown = true

[cache]
backend = "sqlite"
path = ".morphism_cache.db"
read_enabled = false
write_enabled = false

[observability]
log_level = "DEBUG"
log_file = "logs/morphism.log"
```

Environment overlay examples (core-implemented):

bash/zsh:

```bash
export MORPHISM_OLLAMA_URL="http://localhost:11434/api/generate"
export MORPHISM_MODEL_NAME="qwen2.5-coder:1.5b"
export MORPHISM_Z3_TIMEOUT_MS="2000"
export MORPHISM_MAX_SYNTHESIS_ATTEMPTS="3"
export MORPHISM_LLM_REQUEST_TIMEOUT="45"
export MORPHISM_LOG_LEVEL="INFO"
```

PowerShell:

```powershell
$env:MORPHISM_OLLAMA_URL = "http://localhost:11434/api/generate"
$env:MORPHISM_MODEL_NAME = "qwen2.5-coder:1.5b"
$env:MORPHISM_Z3_TIMEOUT_MS = "2000"
$env:MORPHISM_MAX_SYNTHESIS_ATTEMPTS = "3"
$env:MORPHISM_LLM_REQUEST_TIMEOUT = "45"
$env:MORPHISM_LOG_LEVEL = "INFO"
```

## Troubleshooting

### Validation failure examples and remediations

1. Invalid integer env value

Failure:

```text
ValueError: invalid literal for int() with base 10: 'fast'
```

Cause:

- `MORPHISM_Z3_TIMEOUT_MS=fast`

Remediation:

- set numeric string value, e.g. `MORPHISM_Z3_TIMEOUT_MS=2000`.

2. Invalid synthesis endpoint

Failure:

```text
Ollama synthesis failed after 3 retries. Last error: ...
```

Cause:

- bad `MORPHISM_OLLAMA_URL` or unreachable host.

Remediation:

- validate endpoint and network policy; test with simple HTTP probe.

3. Unsupported enum in canonical file

Failure (wrapper strict validation):

```text
profile must be one of: dev, ci, prod, enterprise
```

Cause:

- `profile = "staging"`

Remediation:

- use supported enum or extend wrapper validator contract.

4. Invalid range in canonical file

Failure (wrapper strict validation):

```text
synthesis.max_attempts must be >= 1
```

Cause:

- `synthesis.max_attempts = 0`

Remediation:

- set value >= 1.

5. Policy allowlist parse error

Failure (wrapper strict validation):

```text
allowlisted schema pair must match <Source>-><Target>
```

Cause:

- malformed entry like `Int_0_to_100:Float_Normalized`

Remediation:

- use `Int_0_to_100->Float_Normalized`.

Edge-case notes:

- Unknown config file keys should be fatal in strict wrappers to avoid silent drift.
- In dev wrappers, unknown keys may warn and continue, but this behavior must be explicit.
- When changing model or verification policy, clear cache if deterministic parity is required across runs.
