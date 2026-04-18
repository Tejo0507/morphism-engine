"""morphism.core.native_node – NativeCommandNode wrapping OS subprocesses.

Delegates execution to ``asyncio.create_subprocess_shell``, captures
stdout, and infers the output schema dynamically via
:func:`~morphism.core.inference.infer_schema`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from morphism.core.inference import infer_schema
from morphism.core.node import FunctorNode
from morphism.core.schemas import Pending
from morphism.exceptions import EngineExecutionError
from morphism.utils.logger import get_logger

_log = get_logger("core.native_node")

_STDIO_CHUNK_BYTES = 64 * 1024
_SCHEMA_SAMPLE_BYTES = 128 * 1024
_MAX_STDERR_BYTES = 64 * 1024


def _is_async_iterable(value: Any) -> bool:
    return isinstance(value, AsyncIterable)


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
        """Run the wrapped command and materialize stdout.

        This preserves backward compatibility for callers that expect
        a single in-memory string while internally reusing chunked
        streaming I/O.
        """
        stream = await self.execute_stream(data)
        chunks: list[str] = []
        async for chunk in stream:
            chunks.append(chunk)
        output = "".join(chunks)
        self.output_state = output
        return output

    async def execute_stream(self, data: Any) -> AsyncIterator[str]:
        """Run the command with chunked async I/O and yield stdout text."""
        _log.info("Running native command (streaming): %s", self.cmd_string)

        try:
            proc = await asyncio.create_subprocess_shell(
                self.cmd_string,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise EngineExecutionError(
                f"Failed to launch '{self.cmd_string}': {exc}"
            ) from exc

        if proc.stdout is None or proc.stderr is None:
            raise EngineExecutionError(
                f"Failed to open stdio pipes for '{self.cmd_string}'"
            )

        stderr_buffer = bytearray()
        schema_probe: list[str] = []
        probe_len = 0

        async def _capture_stderr() -> None:
            while True:
                chunk = await proc.stderr.read(_STDIO_CHUNK_BYTES)
                if not chunk:
                    break
                if len(stderr_buffer) < _MAX_STDERR_BYTES:
                    remaining = _MAX_STDERR_BYTES - len(stderr_buffer)
                    stderr_buffer.extend(chunk[:remaining])

        async def _pump_stdin() -> None:
            if proc.stdin is None:
                return
            try:
                async for chunk in self._iter_stdin_bytes(data):
                    proc.stdin.write(chunk)
                    await proc.stdin.drain()
            finally:
                proc.stdin.close()
                if hasattr(proc.stdin, "wait_closed"):
                    with suppress(BrokenPipeError):
                        await proc.stdin.wait_closed()

        def _update_schema_probe(text: str) -> None:
            nonlocal probe_len
            if probe_len >= _SCHEMA_SAMPLE_BYTES:
                return
            room = _SCHEMA_SAMPLE_BYTES - probe_len
            sample = text[:room]
            schema_probe.append(sample)
            probe_len += len(sample)
            self.output_schema = infer_schema("".join(schema_probe))

        stdin_task = asyncio.create_task(_pump_stdin())
        stderr_task = asyncio.create_task(_capture_stderr())

        first_bytes = await proc.stdout.read(_STDIO_CHUNK_BYTES)
        first_chunk = first_bytes.decode(errors="replace")
        if first_chunk:
            _update_schema_probe(first_chunk)

        async def _stream() -> AsyncIterator[str]:
            try:
                if first_chunk:
                    yield first_chunk

                while True:
                    out = await proc.stdout.read(_STDIO_CHUNK_BYTES)
                    if not out:
                        break
                    chunk = out.decode(errors="replace")
                    _update_schema_probe(chunk)
                    yield chunk

                await stdin_task
                await stderr_task
                await proc.wait()

                if not schema_probe:
                    self.output_schema = infer_schema("")

                if proc.returncode != 0:
                    err_text = bytes(stderr_buffer).decode(errors="replace").strip()
                    raise EngineExecutionError(
                        f"Command '{self.cmd_string}' exited with code "
                        f"{proc.returncode}"
                        + (f": {err_text}" if err_text else "")
                    )

                _log.info(
                    "Inferred output schema for '%s': %s",
                    self.cmd_string,
                    self.output_schema.name,
                )
            finally:
                await self._finalize_stream_tasks(proc, stdin_task, stderr_task)

        stream = _stream()
        self.output_state = stream
        return stream

    async def _iter_stdin_bytes(self, data: Any) -> AsyncIterator[bytes]:
        if data is None:
            return

        if isinstance(data, (bytes, bytearray, memoryview)):
            yield bytes(data)
            return

        if isinstance(data, str):
            yield data.encode()
            return

        if _is_async_iterable(data):
            async for chunk in data:
                if chunk is None:
                    continue
                if isinstance(chunk, (bytes, bytearray, memoryview)):
                    yield bytes(chunk)
                else:
                    yield str(chunk).encode()
            return

        yield str(data).encode()

    async def _finalize_stream_tasks(
        self,
        proc: asyncio.subprocess.Process,
        stdin_task: asyncio.Task[Any],
        stderr_task: asyncio.Task[Any],
    ) -> None:
        for task in (stdin_task, stderr_task):
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

        if proc.returncode is None:
            with suppress(ProcessLookupError):
                proc.kill()
            with suppress(Exception):
                await proc.wait()

    def __repr__(self) -> str:
        return (
            f"NativeCommandNode({self.cmd_string!r}, "
            f"out={self.output_schema.name})"
        )
