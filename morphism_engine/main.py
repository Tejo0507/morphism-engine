"""main.py – Morphism Interactive REPL Shell (Phase 6).

A stateful ``cmd.Cmd`` environment that parses piped commands, resolves
type mismatches via the local Ollama LLM + Z3 verifier, and provides
time-travel introspection over the doubly-linked pipeline.

Usage::

    python morphism_engine/main.py
"""

from __future__ import annotations

import cmd
import sys
from pathlib import Path
from typing import Any, Dict, Optional


# ----------------------------------------------------------------------
# Allow running as either:
#   - python -m morphism_engine.main
#   - python morphism_engine/main.py
#
# When run as a script path, Python sets sys.path[0] to the package
# directory (morphism_engine/), which breaks absolute imports of the
# package name. We fix that by inserting the repo root.
# ----------------------------------------------------------------------
if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))


from morphism_engine.node import FunctorNode
from morphism_engine.pipeline import MorphismPipeline, ProofFailedHalt, TypeMismatchHalt
from morphism_engine.schemas import Float_Normalized, Int_0_to_100, Schema, String_NonEmpty
from morphism_engine.live_synthesizer import OllamaSynthesizer


# ======================================================================
# Tool Registry
# ======================================================================
# Each entry maps a command name to a dict with:
#   "func"          – the Python callable
#   "input_schema"  – Schema required on input (None for source nodes)
#   "output_schema" – Schema produced on output

ToolEntry = Dict[str, Any]

TOOL_REGISTRY: Dict[str, ToolEntry] = {
    "emit_raw": {
        "func": lambda x: 50,
        "input_schema": None,
        "output_schema": Int_0_to_100,
    },
    "render_float": {
        "func": lambda x: f"[RENDERED UI]: {x}",
        "input_schema": Float_Normalized,
        "output_schema": String_NonEmpty,
    },
}


# ======================================================================
# Morphism Shell
# ======================================================================

class MorphismShell(cmd.Cmd):
    """Interactive REPL for the Morphism Category Theory pipeline engine.

    Supports ``|``-delimited pipes, AI self-healing, and time-travel
    introspection via ``history`` and ``inspect`` commands.
    """

    intro = (
        "\n"
        "╔══════════════════════════════════════════════════════════════╗\n"
        "║  Morphism v1.0 — Generative Category Shell                 ║\n"
        "║  Type a pipeline:  emit_raw | render_float                 ║\n"
        "║  Commands: history, inspect <n>, tools, help, quit         ║\n"
        "╚══════════════════════════════════════════════════════════════╝\n"
    )
    prompt = "µ> "

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.current_pipeline: Optional[MorphismPipeline] = None

    def cmdloop(self, intro: Optional[str] = None) -> None:  # type: ignore[override]
        """Run the REPL loop, handling Ctrl+C without crashing.

        ``cmd.Cmd`` raises ``KeyboardInterrupt`` on Ctrl+C by default,
        which prints a traceback and exits with code 1. For an
        interactive shell we want to gracefully return to the prompt.
        """
        local_intro = intro
        while True:
            try:
                super().cmdloop(intro=local_intro)
                return
            except KeyboardInterrupt:
                print("\n[Morphism] Interrupted. Type 'quit' to exit.")
                local_intro = None

    # ------------------------------------------------------------------
    # Pipe parser (default handler for unrecognised input)
    # ------------------------------------------------------------------
    def default(self, line: str) -> None:
        """Parse ``tool_a | tool_b | …`` pipelines."""

        # Ignore empty lines
        stripped = line.strip()
        if not stripped:
            return

        segments = [s.strip() for s in stripped.split("|")]
        segments = [s for s in segments if s]  # drop empties

        if not segments:
            return

        # Fresh pipeline per invocation
        synthesizer = OllamaSynthesizer()
        pipeline = MorphismPipeline(llm_client=synthesizer)

        for idx, cmd_name in enumerate(segments, start=1):
            entry = TOOL_REGISTRY.get(cmd_name)
            if entry is None:
                print(
                    f"[Morphism] ERROR: Unknown command '{cmd_name}'. "
                    f"Type 'tools' to see available commands."
                )
                return

            # Build the node's schemas.  For the very first node in
            # a pipeline whose tool has input_schema=None, we use
            # the output_schema as both input and output (source node).
            in_schema: Schema = entry["input_schema"] or entry["output_schema"]
            out_schema: Schema = entry["output_schema"]

            node = FunctorNode(
                input_schema=in_schema,
                output_schema=out_schema,
                executable=entry["func"],
                name=cmd_name,
            )

            try:
                pipeline.append(node)
            except ProofFailedHalt as exc:
                print(f"\n[Morphism] PROOF FAILED — pipeline halted.\n  {exc}")
                return
            except TypeMismatchHalt as exc:
                print(f"\n[Morphism] TYPE MISMATCH — pipeline halted.\n  {exc}")
                return
            except Exception as exc:
                print(f"\n[Morphism] UNEXPECTED ERROR during append:\n  {exc}")
                return

        # Execute the full pipeline.  Source nodes receive None.
        try:
            result = pipeline.execute_all(None)
        except Exception as exc:
            print(f"\n[Morphism] EXECUTION ERROR:\n  {exc}")
            return

        self.current_pipeline = pipeline
        print(f"\n>>> {result}")

    # ------------------------------------------------------------------
    # Built-in commands
    # ------------------------------------------------------------------
    def do_history(self, _arg: str) -> None:
        """Display the node graph of the most recent pipeline."""
        if self.current_pipeline is None or self.current_pipeline.head is None:
            print("[Morphism] No pipeline executed yet.")
            return

        parts: list[str] = []
        node: Optional[FunctorNode] = self.current_pipeline.head
        index = 1
        while node is not None:
            parts.append(f"({index}) {node.name}")
            node = node.next
            index += 1
        print(" -> ".join(parts))

    def do_inspect(self, arg: str) -> None:
        """Inspect the cached output_state of a specific pipeline node.

        Usage: inspect <1-based index>
        """
        if self.current_pipeline is None or self.current_pipeline.head is None:
            print("[Morphism] No pipeline executed yet.")
            return

        try:
            target_idx = int(arg.strip())
        except (ValueError, AttributeError):
            print("[Morphism] Usage: inspect <node number>")
            return

        if target_idx < 1:
            print("[Morphism] Index must be >= 1.")
            return

        node: Optional[FunctorNode] = self.current_pipeline.head
        current = 1
        while node is not None and current < target_idx:
            node = node.next
            current += 1

        if node is None:
            print(
                f"[Morphism] Node {target_idx} does not exist. "
                f"Pipeline has {self.current_pipeline.length} node(s)."
            )
            return

        print(f"[Node {target_idx}] {node.name}")
        print(f"  Schema : {node.input_schema.name} -> {node.output_schema.name}")
        print(f"  State  : {node.output_state!r}")

    def do_tools(self, _arg: str) -> None:
        """List all commands in the tool registry."""
        print("[Morphism] Registered tools:")
        for name, entry in TOOL_REGISTRY.items():
            in_s = entry["input_schema"]
            out_s = entry["output_schema"]
            in_name = in_s.name if in_s else "None (source)"
            print(f"  {name:20s}  {in_name} -> {out_s.name}")

    def do_quit(self, _arg: str) -> bool:
        """Exit the Morphism shell."""
        print("[Morphism] Goodbye.")
        return True

    do_exit = do_quit
    do_EOF = do_quit


# ======================================================================
# Entrypoint
# ======================================================================

if __name__ == "__main__":
    MorphismShell().cmdloop()
