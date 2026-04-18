"""morphism.config – Centralised configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MorphismConfig:
    """Immutable runtime configuration.

    Every field can be overridden by setting the corresponding
    environment variable (uppercased, prefixed ``MORPHISM_``).
    """

    ollama_url: str = field(
        default_factory=lambda: os.getenv(
            "MORPHISM_OLLAMA_URL", "http://localhost:11434/api/generate"
        )
    )
    model_name: str = field(
        default_factory=lambda: os.getenv(
            "MORPHISM_MODEL_NAME", "qwen2.5-coder:1.5b"
        )
    )
    z3_timeout_ms: int = field(
        default_factory=lambda: int(os.getenv("MORPHISM_Z3_TIMEOUT_MS", "2000"))
    )
    log_level: str = field(
        default_factory=lambda: os.getenv("MORPHISM_LOG_LEVEL", "INFO")
    )
    max_synthesis_attempts: int = field(
        default_factory=lambda: int(
            os.getenv("MORPHISM_MAX_SYNTHESIS_ATTEMPTS", "6")
        )
    )
    llm_request_timeout: int = field(
        default_factory=lambda: int(
            os.getenv("MORPHISM_LLM_REQUEST_TIMEOUT", "60")
        )
    )
    stream_mode: str = field(
        default_factory=lambda: os.getenv("MORPHISM_STREAM_MODE", "auto").lower()
    )
    stream_auto_for_native: bool = field(
        default_factory=lambda: os.getenv(
            "MORPHISM_STREAM_AUTO_FOR_NATIVE", "true"
        ).lower() in {"1", "true", "yes", "on"}
    )
    proof_certificate_dir: str = field(
        default_factory=lambda: os.getenv(
            "MORPHISM_PROOF_CERT_DIR", "logs/proofs"
        )
    )
    arrow_enabled: bool = field(
        default_factory=lambda: os.getenv("MORPHISM_ARROW_ENABLED", "true").lower()
        in {"1", "true", "yes", "on"}
    )


# Module-level singleton – import this everywhere.
config = MorphismConfig()
