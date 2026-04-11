"""test_phase6_shell.py – Phase 6: Interactive REPL Shell integration tests.

Tests programmatically drive ``MorphismShell.onecmd()`` while capturing
stdout into an ``io.StringIO`` buffer, then assert on the expected
Morphism engine log lines and final output.

Requires a running Ollama instance with ``qwen2.5-coder:1.5b``.
"""

from __future__ import annotations

import io
import sys

import pytest
import requests

from morphism_engine.main import MorphismShell


# ======================================================================
# Helper: skip entire module if Ollama is not reachable
# ======================================================================

def _ollama_is_alive(base_url: str = "http://localhost:11434") -> bool:
    try:
        r = requests.get(base_url, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _ollama_is_alive(),
    reason="Ollama server not reachable at localhost:11434",
)


# ======================================================================
# Test A – Full pipe through the REPL
# ======================================================================

def test_repl_pipe_emit_render() -> None:
    """Drive ``emit_raw | render_float`` through the shell and verify:
    1. Z3 proof passed (AI bridged Int_0_to_100 → Float_Normalized).
    2. Final output is ``[RENDERED UI]: 0.5``.
    """
    shell = MorphismShell()
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf

    try:
        shell.onecmd("emit_raw | render_float")
    finally:
        sys.stdout = old_stdout

    captured = buf.getvalue()
    print("--- captured stdout ---")
    print(captured)
    print("--- end ---")

    assert "[Z3] PROOF PASSED" in captured, (
        f"Expected Z3 proof log in output. Got:\n{captured}"
    )
    assert "[RENDERED UI]: 0.5" in captured, (
        f"Expected rendered output in output. Got:\n{captured}"
    )


# ======================================================================
# Test B – Unknown command graceful error
# ======================================================================

def test_repl_unknown_command() -> None:
    """Typing an unknown command should print an error, not crash."""
    shell = MorphismShell()
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf

    try:
        shell.onecmd("nonexistent_tool | render_float")
    finally:
        sys.stdout = old_stdout

    captured = buf.getvalue()
    assert "ERROR" in captured
    assert "nonexistent_tool" in captured


# ======================================================================
# Test C – History and inspect commands
# ======================================================================

def test_repl_history_and_inspect() -> None:
    """After a successful pipe, ``history`` and ``inspect`` should work."""
    shell = MorphismShell()

    # Suppress pipe output
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        shell.onecmd("emit_raw | render_float")
    finally:
        sys.stdout = old_stdout

    # Now test history
    buf2 = io.StringIO()
    sys.stdout = buf2
    try:
        shell.onecmd("history")
    finally:
        sys.stdout = old_stdout

    history_out = buf2.getvalue()
    print("--- history ---")
    print(history_out)
    # Should contain all three nodes
    assert "emit_raw" in history_out
    assert "AI_Bridge_Functor" in history_out
    assert "render_float" in history_out

    # Test inspect on node 2 (the AI bridge)
    buf3 = io.StringIO()
    sys.stdout = buf3
    try:
        shell.onecmd("inspect 2")
    finally:
        sys.stdout = old_stdout

    inspect_out = buf3.getvalue()
    print("--- inspect 2 ---")
    print(inspect_out)
    assert "AI_Bridge_Functor" in inspect_out
    assert "0.5" in inspect_out
