"""test_phase3_4.py – End-to-end tests for the LLM Synthesizer and
self-healing pipeline (Phases 3 & 4)."""

from __future__ import annotations

import pytest

from morphism_engine.schemas import Int_0_to_100, Float_Normalized, Int_0_to_10
from morphism_engine.node import FunctorNode
from morphism_engine.pipeline import MorphismPipeline, ProofFailedHalt
from morphism_engine.synthesizer import MockLLMSynthesizer


# ======================================================================
# Test A – The Self-Healing Pipe
# ======================================================================

def test_self_healing_pipe() -> None:
    """When a type-mismatch occurs and an LLM client is present, the
    pipeline must autonomously:

    1. Synthesise a bridge functor via the LLM.
    2. Formally verify it with Z3.
    3. JIT-compile and inject it as an ``AI_Bridge_Functor`` node.

    Resulting linked list:  Node1 → AI_Bridge_Functor → Node2  (length 3).
    Executing with input ``50`` must yield ``0.5`` at the tail.
    """
    pipeline = MorphismPipeline(llm_client=MockLLMSynthesizer())

    node_1 = FunctorNode(
        input_schema=Int_0_to_100,
        output_schema=Int_0_to_100,
        executable=lambda x: x,          # identity – pass-through
        name="source_int",
    )
    node_2 = FunctorNode(
        input_schema=Float_Normalized,
        output_schema=Float_Normalized,
        executable=lambda x: x,          # identity – pass-through
        name="sink_float",
    )

    # --- Append Node 1 (no mismatch yet) ---
    assert pipeline.append(node_1) is True

    # --- Append Node 2 (mismatch: Int_0_to_100 ≠ Float_Normalized) ---
    # The pipeline must heal itself automatically.
    assert pipeline.append(node_2) is True

    # Assertion 1: length is 3 (node_1 + bridge + node_2)
    assert pipeline.length == 3, f"Expected length 3, got {pipeline.length}"

    # Assertion 2: the middle node is the AI bridge
    bridge = node_1.next
    assert bridge is not None
    assert bridge.name == "AI_Bridge_Functor"
    assert bridge.input_schema == Int_0_to_100
    assert bridge.output_schema == Float_Normalized
    assert bridge.next is node_2
    assert node_2.prev is bridge

    # Assertion 3: execute the full pipeline with input 50
    result = pipeline.execute_all(50)
    assert result == 0.5, f"Expected 0.5, got {result}"


# ======================================================================
# Test B – The Unsafe Hallucination (ProofFailedHalt)
# ======================================================================

def test_unsafe_hallucination_blocked() -> None:
    """When the LLM returns an out-of-bounds functor (``x * 999.0``),
    Z3 must reject it and the pipeline must raise ``ProofFailedHalt``
    without mutating the linked list."""
    pipeline = MorphismPipeline(llm_client=MockLLMSynthesizer())

    node_1 = FunctorNode(
        input_schema=Int_0_to_100,
        output_schema=Int_0_to_100,
        executable=lambda x: x,
        name="source_int",
    )
    # This node expects Int_0_to_10 – the mock does NOT know this
    # pair, so it will return the unsafe "lambda x: x * 999.0".
    node_bad = FunctorNode(
        input_schema=Int_0_to_10,
        output_schema=Int_0_to_10,
        executable=lambda x: x,
        name="sink_int_0_10",
    )

    pipeline.append(node_1)

    with pytest.raises(ProofFailedHalt):
        pipeline.append(node_bad)

    # Pipeline must remain unlinked – only node_1 present
    assert pipeline.length == 1
    assert pipeline.tail is node_1
    assert node_1.next is None
