"""synthesizer.py – LLM Synthesizer for generating bridge functors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from morphism_engine.schemas import Schema


# ======================================================================
# Base class
# ======================================================================

class LLMSynthesizer(ABC):
    """Abstract base for any LLM backend that generates functor code.

    Subclasses must implement :meth:`generate_functor`, which accepts
    a *source* and *target* :class:`Schema` and returns a Python
    expression string (e.g. ``"lambda x: x / 100.0"``) that can be
    compiled via ``eval()``.
    """

    @abstractmethod
    def generate_functor(self, source: Schema, target: Schema) -> str:
        """Return a Python lambda/expression string that maps values
        from *source* domain into *target* domain."""
        ...


# ======================================================================
# Deterministic mock for local testing (no API keys required)
# ======================================================================

class MockLLMSynthesizer(LLMSynthesizer):
    """A fully deterministic mock that returns known code strings
    for pre-defined schema pairs, and a deliberately unsafe fallback
    for anything else.

    Known mappings
    --------------
    * ``Int_0_to_100 → Float_Normalized``:  ``"lambda x: x / 100.0"``

    Fallback (unknown pair)
    -----------------------
    * ``"lambda x: x * 999.0"``  — intentionally violates most bounds
      so that Z3 rejects it, exercising the safety boundary.
    """

    def generate_functor(self, source: Schema, target: Schema) -> str:
        if source.name == "Int_0_to_100" and target.name == "Float_Normalized":
            code: str = "lambda x: x / 100.0"
            print(
                f"[MockLLM] Synthesised Functor "
                f"F({source.name} -> {target.name}): {code}"
            )
            return code

        # Unknown mapping → intentionally unsafe code
        code = "lambda x: x * 999.0"
        print(
            f"[MockLLM] Synthesised (UNSAFE) Functor "
            f"F({source.name} -> {target.name}): {code}"
        )
        return code
