"""morphism.cli.shell – Interactive REPL bridging sync cmd.Cmd to async engine.

Supports both linear pipes (``|``) and branching (``|+``).

Usage::

    python -m morphism.cli.shell
    # or via the ``morphism`` console_script entry point.
"""

from __future__ import annotations

import asyncio
import cmd
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from morphism.ai.synthesizer import OllamaSynthesizer
from morphism.config import config
from morphism.core.native_node import NativeCommandNode
from morphism.core.node import FunctorNode
from morphism.core.pipeline import MorphismPipeline
from morphism.core.schemas import (
    Float_Normalized,
    Int_0_to_100,
    Schema,
    String_NonEmpty,
)
from morphism.exceptions import MorphismError
from morphism.utils.logger import get_logger, setup_logging

_log = get_logger("cli.shell")

# ANSI helpers
_RED = "\033[91m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_RESET = "\033[0m"

# ======================================================================
# Tool Registry
# ======================================================================
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


def _make_node(cmd_name: str) -> FunctorNode:
    """Create a FunctorNode or NativeCommandNode for *cmd_name*."""
    entry = TOOL_REGISTRY.get(cmd_name)
    if entry is not None:
        in_schema: Schema = entry["input_schema"] or entry["output_schema"]
        out_schema: Schema = entry["output_schema"]
        return FunctorNode(
            input_schema=in_schema,
            output_schema=out_schema,
            executable=entry["func"],
            name=cmd_name,
        )
    _log.info(
        "Command '%s' not in TOOL_REGISTRY — delegating to native subprocess.",
        cmd_name,
    )
    return NativeCommandNode.from_command(cmd_name)


# ======================================================================
# Shell
# ======================================================================

class MorphismShell(cmd.Cmd):
    """Interactive REPL with ``|`` / ``|+`` pipes and AI self-healing."""

    intro = (
        "\n"
        f"{_CYAN}"
        "╔══════════════════════════════════════════════════════════════╗\n"
        "║  Morphism v3.0 — Generative Category Shell (DAG + Cache)   ║\n"
        "║  Linear:  emit_raw | render_float                          ║\n"
        "║  Branch:  emit_raw |+ (render_float, render_float)         ║\n"
        "║  Commands: history, inspect <n>, tools, help, quit         ║\n"
        "╚══════════════════════════════════════════════════════════════╝"
        f"{_RESET}\n"
    )
    prompt = "µ> "

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.current_pipeline: Optional[MorphismPipeline] = None
        self._stream_mode = self._normalize_stream_mode(config.stream_mode)

    def cmdloop(self, intro: Optional[str] = None) -> None:
        """Handle Ctrl+C gracefully."""
        local_intro = intro
        while True:
            try:
                super().cmdloop(intro=local_intro)
                return
            except KeyboardInterrupt:
                sys.stdout.write(
                    f"\n{_YELLOW}[Morphism] Interrupted. "
                    f"Type 'quit' to exit.{_RESET}\n"
                )
                local_intro = None

    # ------------------------------------------------------------------
    # Pipe parser
    # ------------------------------------------------------------------
    def default(self, line: str) -> None:
        stripped = line.strip()
        if not stripped:
            return

        try:
            asyncio.run(self._async_process_pipeline(stripped))
        except MorphismError as exc:
            _log.error("Pipeline error: %s", exc, exc_info=True)
            sys.stdout.write(
                f"{_RED}[Morphism] ERROR: {exc} "
                f"(command: {stripped}){_RESET}\n"
            )
        except Exception as exc:
            _log.error("Unexpected error: %s", exc, exc_info=True)
            sys.stdout.write(
                f"{_RED}[Morphism] UNEXPECTED ERROR: {exc} "
                f"(command: {stripped}){_RESET}\n"
            )

    async def _async_process_pipeline(self, line: str) -> None:
        synthesizer = OllamaSynthesizer()
        pipeline = MorphismPipeline(llm_client=synthesizer)

        # ── Detect branch operator |+ ────────────────────────────────
        branch_match = re.match(
            r"^(.+?)\s*\|\+\s*\((.+)\)\s*$", line,
        )
        if branch_match:
            prefix = branch_match.group(1).strip()
            branch_body = branch_match.group(2).strip()

            # Build linear prefix
            prefix_segments = [s.strip() for s in prefix.split("|") if s.strip()]
            for cmd_name in prefix_segments:
                await pipeline.append(_make_node(cmd_name))

            # Build branch children
            child_names = [c.strip() for c in branch_body.split(",") if c.strip()]
            children = [_make_node(c) for c in child_names]
            parent = pipeline.tail
            assert parent is not None
            await pipeline.add_branch(parent, children)

            await self._execute_pipeline_with_mode(pipeline)
            return

        # ── Linear pipe (classic) ────────────────────────────────────
        segments = [s.strip() for s in line.split("|") if s.strip()]
        if not segments:
            return

        for cmd_name in segments:
            await pipeline.append(_make_node(cmd_name))

        await self._execute_pipeline_with_mode(pipeline)

    async def _execute_pipeline_with_mode(self, pipeline: MorphismPipeline) -> None:
        if self._should_stream_pipeline(pipeline):
            stream = await pipeline.execute_all_stream(None)
            preview_parts: list[str] = []
            preview_budget = 8192
            sys.stdout.write("\n>>> ")
            async for item in stream:
                text = item if isinstance(item, str) else str(item)
                sys.stdout.write(text)
                if preview_budget > 0:
                    keep = text[:preview_budget]
                    preview_parts.append(keep)
                    preview_budget -= len(keep)
            sys.stdout.write("\n")
            if pipeline.tail is not None and preview_parts:
                pipeline.tail.output_state = "".join(preview_parts)
        else:
            result = await pipeline.execute_all(None)
            sys.stdout.write(f"\n>>> {result}\n")

        self.current_pipeline = pipeline

    def _should_stream_pipeline(self, pipeline: MorphismPipeline) -> bool:
        mode = self._stream_mode
        if mode == "on":
            return True
        if mode == "off":
            return False
        if not config.stream_auto_for_native:
            return False
        return any(isinstance(node, NativeCommandNode) for node in pipeline.all_nodes)

    @staticmethod
    def _normalize_stream_mode(mode: str) -> str:
        lowered = mode.strip().lower()
        return lowered if lowered in {"on", "off", "auto"} else "auto"

    # ------------------------------------------------------------------
    # Built-in commands
    # ------------------------------------------------------------------
    def do_history(self, _arg: str) -> None:
        if self.current_pipeline is None or not self.current_pipeline.all_nodes:
            sys.stdout.write("[Morphism] No pipeline executed yet.\n")
            return
        parts: list[str] = []
        for idx, node in enumerate(self.current_pipeline.all_nodes, 1):
            parts.append(f"({idx}) {node.name}")
        sys.stdout.write(" -> ".join(parts) + "\n")

    def do_inspect(self, arg: str) -> None:
        if self.current_pipeline is None or not self.current_pipeline.all_nodes:
            sys.stdout.write("[Morphism] No pipeline executed yet.\n")
            return
        try:
            target = int(arg.strip())
        except (ValueError, AttributeError):
            sys.stdout.write("[Morphism] Usage: inspect <node number>\n")
            return
        if target < 1 or target > len(self.current_pipeline.all_nodes):
            sys.stdout.write(
                f"[Morphism] Node {target} does not exist. "
                f"Pipeline has {self.current_pipeline.length} node(s).\n"
            )
            return
        node = self.current_pipeline.all_nodes[target - 1]
        sys.stdout.write(f"[Node {target}] {node.name}\n")
        sys.stdout.write(
            f"  Schema : {node.input_schema.name} -> {node.output_schema.name}\n"
        )
        sys.stdout.write(f"  State  : {node.output_state!r}\n")

    def do_tools(self, _arg: str) -> None:
        sys.stdout.write("[Morphism] Registered tools:\n")
        for name, entry in TOOL_REGISTRY.items():
            in_s = entry["input_schema"]
            out_s = entry["output_schema"]
            in_name = in_s.name if in_s else "None (source)"
            sys.stdout.write(f"  {name:20s}  {in_name} -> {out_s.name}\n")

    def do_stream(self, arg: str) -> None:
        mode = arg.strip().lower()
        if not mode:
            sys.stdout.write(
                "[Morphism] Stream mode is "
                f"'{self._stream_mode}' (valid: auto, on, off).\n"
            )
            return

        if mode not in {"auto", "on", "off"}:
            sys.stdout.write("[Morphism] Usage: stream [auto|on|off]\n")
            return

        self._stream_mode = mode
        sys.stdout.write(f"[Morphism] Stream mode set to '{self._stream_mode}'.\n")

    def do_quit(self, _arg: str) -> bool:
        sys.stdout.write("[Morphism] Goodbye.\n")
        return True

    do_exit = do_quit
    do_EOF = do_quit


# ======================================================================
# Entry point
# ======================================================================

def main() -> None:
    setup_logging(config.log_level)
    MorphismShell().cmdloop()


if __name__ == "__main__":
    main()
