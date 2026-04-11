"""node.py – FunctorNode: the doubly-linked-list element of a Morphism pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from morphism_engine.schemas import Schema


@dataclass
class FunctorNode:
    """A single transformation step in a Morphism pipeline.

    Each node behaves as an element of a **doubly linked list** and carries:

    * ``input_schema`` / ``output_schema`` – the categorical source and target
      objects that constrain which morphisms may compose.
    * ``executable`` – the actual transformation ``Callable[[Any], Any]``.
    * ``output_state`` – a cached snapshot of the last execution result,
      enabling time-travel debugging (replay / rollback).
    * ``prev`` / ``next`` – DLL pointers.
    """

    input_schema: Schema
    output_schema: Schema
    executable: Callable[[Any], Any]
    name: str = "anonymous"

    # DLL pointers
    prev: Optional["FunctorNode"] = field(default=None, repr=False, compare=False)
    next: Optional["FunctorNode"] = field(default=None, repr=False, compare=False)

    # Cached execution result
    output_state: Optional[Any] = field(default=None, repr=False, compare=False)

    # ------------------------------------------------------------------
    def execute(self, data: Any) -> Any:
        """Run the node's executable, cache the result, and return it."""
        result: Any = self.executable(data)
        self.output_state = result
        return result

    def __repr__(self) -> str:
        return (
            f"FunctorNode({self.name!r}, "
            f"in={self.input_schema.name}, out={self.output_schema.name})"
        )
