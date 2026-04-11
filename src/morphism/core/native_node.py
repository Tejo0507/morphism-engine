"""morphism.core.native_node – NativeCommandNode wrapping OS subprocesses.

Delegates execution to ``asyncio.create_subprocess_shell``, captures
stdout, and infers the output schema dynamically via
:func:`~morphism.core.inference.infer_schema`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from morphism.core.inference import infer_schema
from morphism.core.node import FunctorNode
from morphism.core.schemas import Pending
from morphism.exceptions import EngineExecutionError
from morphism.utils.logger import get_logger

_log = get_logger("core.native_node")


@dataclass
class NativeCommandNode(FunctorNode):
    """A pipeline node backed by a native OS subprocess.

    Both ``input_schema`` and ``output_schema`` start as
    :data:`~morphism.core.schemas.Pending`.  After execution the
    output schema is resolved via schema inference on stdout.
    """

    cmd_string: str = ""

    # ── Factory ──────────────────────────────────────────────────────

    @classmethod
    def from_command(cls, cmd: str) -> "NativeCommandNode":
        """Create a node for *cmd* with ``Pending`` schemas."""
        return cls(
            input_schema=Pending,
            output_schema=Pending,
            executable=lambda x: x,  # placeholder – execute() is overridden
            name=cmd,
            cmd_string=cmd,
        )

    # ── Execution ────────────────────────────────────────────────────

    async def execute(self, data: Any) -> Any:  # type: ignore[override]
        """Run the wrapped command, capture stdout, and infer schema."""
        _log.info("Running native command: %s", self.cmd_string)

        stdin_bytes: bytes | None = None
        if data is not None:
            stdin_bytes = str(data).encode()

        try:
            proc = await asyncio.create_subprocess_shell(
                self.cmd_string,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_raw, stderr_raw = await proc.communicate(
                input=stdin_bytes,
            )
        except OSError as exc:
            raise EngineExecutionError(
                f"Failed to launch '{self.cmd_string}': {exc}"
            ) from exc

        if proc.returncode != 0:
            err_text = stderr_raw.decode(errors="replace").strip()
            raise EngineExecutionError(
                f"Command '{self.cmd_string}' exited with code "
                f"{proc.returncode}"
                + (f": {err_text}" if err_text else "")
            )

        output = stdout_raw.decode(errors="replace")
        _log.debug(
            "Captured %d bytes from '%s'", len(output), self.cmd_string,
        )

        # Resolve Pending → concrete schema
        self.output_schema = infer_schema(output)
        _log.info(
            "Inferred output schema for '%s': %s",
            self.cmd_string,
            self.output_schema.name,
        )

        self.output_state = output
        return output

    def __repr__(self) -> str:
        return (
            f"NativeCommandNode({self.cmd_string!r}, "
            f"out={self.output_schema.name})"
        )
