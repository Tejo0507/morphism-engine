"""test_phase2.py – Phase 2 tests: Z3 formal verification of functor mappings."""

from __future__ import annotations

from morphism_engine.schemas import Int_0_to_100, Float_Normalized
from morphism_engine.z3_verifier import verify_functor_mapping


# ======================================================================
# Test A – Valid functor: x / 100.0  maps Int[0,100] → Float[0,1]
# ======================================================================

def test_valid_functor_mapping() -> None:
    """The transformation ``lambda x: x / 100.0`` should be proven safe
    by Z3 (output always in [0.0, 1.0])."""
    result = verify_functor_mapping(
        source_schema=Int_0_to_100,
        target_schema=Float_Normalized,
        transformation_logic=lambda x: x / 100.0,
    )
    assert result is True


# ======================================================================
# Test B – Invalid functor: x / 50.0  maps Int[0,100] → Float[0,2]
# ======================================================================

def test_invalid_functor_mapping() -> None:
    """The transformation ``lambda x: x / 50.0`` can produce 2.0 which
    violates Float_Normalized bounds.  Z3 must detect this."""
    result = verify_functor_mapping(
        source_schema=Int_0_to_100,
        target_schema=Float_Normalized,
        transformation_logic=lambda x: x / 50.0,
    )
    assert result is False
