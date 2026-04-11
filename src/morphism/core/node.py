"""morphism.core.node – Async FunctorNode: DAG vertex."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from morphism.core.schemas import Schema
from morphism.utils.logger import get_logger

_log = get_logger("core.node")


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
        result: Any = self.executable(data)
        self.output_state = result
        _log.debug("Node %r produced output %r", self.name, result)
        return result

    def __repr__(self) -> str:
        return (
            f"FunctorNode({self.name!r}, "
            f"in={self.input_schema.name}, out={self.output_schema.name})"
        )
