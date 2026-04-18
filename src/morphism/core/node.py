"""morphism.core.node – Async FunctorNode: DAG vertex."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from morphism.core.schemas import Schema
from morphism.utils.logger import get_logger

_log = get_logger("core.node")


def _is_async_iterable(value: Any) -> bool:
    return isinstance(value, AsyncIterable)


@dataclass
class FunctorNode:
    """A single transformation step in a Morphism pipeline.

    Each node is a vertex in a **directed acyclic graph** carrying:

    * ``input_schema`` / ``output_schema`` – categorical source & target.
    * ``executable`` – transformation ``Callable[[Any], Any]``.
    * ``output_state`` – cached last execution result (time-travel).
    * ``parents`` / ``children`` – DAG adjacency lists.
    """

    input_schema: Schema
    output_schema: Schema
    executable: Callable[[Any], Any]
    name: str = "anonymous"
    supports_arrow: bool = False

    # DAG pointers (replaced former DLL prev/next)
    parents: list["FunctorNode"] = field(default_factory=list, repr=False, compare=False)
    children: list["FunctorNode"] = field(default_factory=list, repr=False, compare=False)

    # Cached execution result
    output_state: Optional[Any] = field(default=None, repr=False, compare=False)

    # ------------------------------------------------------------------
    def append_child(self, child: "FunctorNode") -> None:
        """Establish a bidirectional parent→child edge."""
        if child not in self.children:
            self.children.append(child)
        if self not in child.parents:
            child.parents.append(self)

    # ------------------------------------------------------------------
    async def execute(self, data: Any) -> Any:
        """Run the node's executable, cache the result, and return it."""
        _log.debug("Executing node %r with input %r", self.name, data)

        if _is_async_iterable(data):
            result = self._map_stream(data)
            self.output_state = result
            _log.debug("Node %r produced streamed output", self.name)
            return result

        result = await self._invoke_executable(data)
        self.output_state = result
        _log.debug("Node %r produced output %r", self.name, result)
        return result

    async def execute_stream(self, data: Any) -> AsyncIterator[Any]:
        """Run this node lazily and return an async iterator of outputs."""
        _log.debug("Streaming node %r with input %r", self.name, data)

        if _is_async_iterable(data):
            stream = self._map_stream(data)
            self.output_state = stream
            return stream

        result = await self._invoke_executable(data)
        if _is_async_iterable(result):
            self.output_state = result
            return result

        async def _single() -> AsyncIterator[Any]:
            yield result

        stream = _single()
        self.output_state = stream
        return stream

    async def _invoke_executable(self, payload: Any) -> Any:
        from morphism.core.transport import normalize_node_input

        normalized = normalize_node_input(payload, self)
        result = self.executable(normalized)
        if inspect.isawaitable(result):
            return await result
        return result

    async def _map_stream(self, stream: AsyncIterable[Any]) -> AsyncIterator[Any]:
        async for item in stream:
            mapped = await self._invoke_executable(item)
            if _is_async_iterable(mapped):
                async for nested in mapped:
                    yield nested
            else:
                yield mapped

    def __repr__(self) -> str:
        return (
            f"FunctorNode({self.name!r}, "
            f"in={self.input_schema.name}, out={self.output_schema.name})"
        )
