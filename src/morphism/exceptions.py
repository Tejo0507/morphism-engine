"""morphism.exceptions – Strict exception hierarchy for the Morphism engine."""

from __future__ import annotations


class MorphismError(Exception):
    """Base class for all Morphism-specific errors."""


class SchemaMismatchError(MorphismError):
    """Raised when a pipeline node's input schema does not match the
    preceding node's output schema and no LLM client is available to
    heal the gap."""


class SynthesisTimeoutError(MorphismError):
    """Raised when the LLM synthesiser fails to produce usable code
    after exhausting all retry attempts."""


class VerificationFailedError(MorphismError):
    """Raised when the Z3 SMT solver rejects the AI-generated functor
    or fails to reach a verdict within the configured timeout."""


class EngineExecutionError(MorphismError):
    """Raised when the pipeline encounters a runtime error during
    node execution (e.g. a TypeError inside a compiled functor)."""
