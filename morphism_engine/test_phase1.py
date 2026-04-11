"""test_phase1.py – Phase 1 tests: Schema primitives, FunctorNode, Pipeline linking."""

from __future__ import annotations

import pytest

from morphism_engine.schemas import Int_0_to_100, Float_Normalized, String_NonEmpty
from morphism_engine.node import FunctorNode
from morphism_engine.pipeline import MorphismPipeline, TypeMismatchHalt


# ======================================================================
# Test A – Compatible append succeeds and DLL is correctly linked
# ======================================================================

def test_append_compatible_nodes() -> None:
    """Two nodes whose schemas match should link successfully."""
    pipeline = MorphismPipeline()

    node_a = FunctorNode(
        input_schema=Int_0_to_100,
        output_schema=Int_0_to_100,
        executable=lambda x: x + 1,
        name="increment",
    )
    node_b = FunctorNode(
        input_schema=Int_0_to_100,
        output_schema=Int_0_to_100,
        executable=lambda x: x * 2,
        name="double",
    )

    assert pipeline.append(node_a) is True
    assert pipeline.append(node_b) is True

    # Verify linked-list structure
    assert pipeline.head is node_a
    assert pipeline.tail is node_b
    assert node_a.next is node_b
    assert node_b.prev is node_a
    assert pipeline.length == 2


# ======================================================================
# Test B – Incompatible append raises TypeMismatchHalt
# ======================================================================

def test_append_incompatible_node_raises() -> None:
    """Appending a node whose input_schema mismatches the tail's
    output_schema must raise ``TypeMismatchHalt``."""
    pipeline = MorphismPipeline()

    node_a = FunctorNode(
        input_schema=Int_0_to_100,
        output_schema=Int_0_to_100,
        executable=lambda x: x + 1,
        name="increment",
    )
    node_b = FunctorNode(
        input_schema=Int_0_to_100,
        output_schema=Int_0_to_100,
        executable=lambda x: x * 2,
        name="double",
    )
    node_bad = FunctorNode(
        input_schema=Float_Normalized,
        output_schema=Float_Normalized,
        executable=lambda x: x * 0.5,
        name="halve_float",
    )

    pipeline.append(node_a)
    pipeline.append(node_b)

    with pytest.raises(TypeMismatchHalt):
        pipeline.append(node_bad)

    # Ensure the pipeline was NOT mutated
    assert pipeline.length == 2
    assert pipeline.tail is node_b
    assert node_b.next is None


# ======================================================================
# Test C – Execution and time-travel (maps_back / maps_forward)
# ======================================================================

def test_execute_and_time_travel() -> None:
    """Pipeline should execute sequentially, caching each output_state,
    and the traversal helpers should walk correctly."""
    pipeline = MorphismPipeline()

    node_a = FunctorNode(
        input_schema=Int_0_to_100,
        output_schema=Int_0_to_100,
        executable=lambda x: x + 10,
        name="add_10",
    )
    node_b = FunctorNode(
        input_schema=Int_0_to_100,
        output_schema=Int_0_to_100,
        executable=lambda x: x * 2,
        name="double",
    )

    pipeline.append(node_a)
    pipeline.append(node_b)

    result = pipeline.execute_all(5)
    assert result == 30  # (5 + 10) * 2

    # Time-travel back
    assert pipeline.maps_back() == 15  # node_a's output_state
    # Time-travel forward
    assert pipeline.maps_forward() == 30  # node_b's output_state
