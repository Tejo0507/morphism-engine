"""test_phase5_local.py – Phase 5: Live Local LLM integration tests.

These tests require a running Ollama instance with the ``qwen2.5-coder:1.5b``
model pulled.  They are automatically skipped if Ollama is not reachable.
"""

from __future__ import annotations

import pytest
import requests

from morphism_engine.schemas import Int_0_to_100, Float_Normalized
from morphism_engine.node import FunctorNode
from morphism_engine.pipeline import MorphismPipeline
from morphism_engine.live_synthesizer import OllamaSynthesizer


# ======================================================================
# Helper: skip entire module if Ollama is not reachable
# ======================================================================

def _ollama_is_alive(base_url: str = "http://localhost:11434") -> bool:
    try:
        r = requests.get(base_url, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


# Module-level skip
pytestmark = pytest.mark.skipif(
    not _ollama_is_alive(),
    reason="Ollama server not reachable at localhost:11434",
)


# ======================================================================
# Test A – Live Local Self-Healing Pipe
# ======================================================================

def test_live_local_healing() -> None:
    """End-to-end: Ollama synthesises a bridge functor, Z3 verifies it,
    the pipeline heals itself, and execution produces the correct output.

    Pipeline:
        Node1 (Int_0_to_100 → Int_0_to_100)
            ↓ mismatch detected
        AI_Bridge_Functor (Int_0_to_100 → Float_Normalized)  ← LLM + Z3
            ↓
        Node2 (Float_Normalized → Float_Normalized)

    Input 50 → expected output 0.5
    """
    synthesizer = OllamaSynthesizer()
    pipeline = MorphismPipeline(llm_client=synthesizer)

    node_1 = FunctorNode(
        input_schema=Int_0_to_100,
        output_schema=Int_0_to_100,
        executable=lambda x: x,          # identity
        name="source_int",
    )
    node_2 = FunctorNode(
        input_schema=Float_Normalized,
        output_schema=Float_Normalized,
        executable=lambda x: x,          # identity
        name="sink_float",
    )

    # Append node_1 – no mismatch
    assert pipeline.append(node_1) is True

    # Append node_2 – mismatch triggers LLM synthesis → Z3 verify → inject
    assert pipeline.append(node_2) is True

    # The pipeline should now be length 3
    assert pipeline.length == 3, f"Expected 3 nodes, got {pipeline.length}"

    # The middle node should be the AI bridge
    bridge = node_1.next
    assert bridge is not None
    assert bridge.name == "AI_Bridge_Functor"

    # Execute the full pipeline: 50 → 50 → 0.5 → 0.5
    result = pipeline.execute_all(50)
    assert result == pytest.approx(0.5, abs=1e-6), f"Expected ≈0.5, got {result}"

    print(f"\n[Phase 5] LIVE TEST PASSED: execute_all(50) = {result}")
    print(f"[Phase 5] Pipeline state: {pipeline.length} nodes")
    print(f"[Phase 5] Bridge functor: {bridge}")
