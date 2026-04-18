"""morphism.core.transport – Optional Arrow transport adaptation for node payloads.

This module provides a best-effort Arrow path when `pyarrow` is available
and both producer/consumer nodes opt-in via `supports_arrow=True`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from morphism.config import config
from morphism.utils.logger import get_logger

_log = get_logger("core.transport")

try:
    import pyarrow as pa
except Exception:  # pragma: no cover - optional dependency
    pa = None


@dataclass(frozen=True)
class ArrowPayload:
    """In-memory Arrow table wrapper for typed node-to-node transport."""

    table: Any

    def to_pylist(self) -> list[dict[str, Any]]:
        if hasattr(self.table, "to_pylist"):
            return self.table.to_pylist()
        raise TypeError("ArrowPayload.table does not support to_pylist()")


def arrow_available() -> bool:
    return bool(config.arrow_enabled and pa is not None)


def _is_arrow_table(value: Any) -> bool:
    if pa is None:
        return False
    return isinstance(value, pa.Table)


def _to_arrow_payload(value: Any) -> Any:
    if not arrow_available():
        return value

    if isinstance(value, ArrowPayload):
        return value

    if _is_arrow_table(value):
        return ArrowPayload(value)

    if isinstance(value, list) and value and all(isinstance(row, dict) for row in value):
        try:
            table = pa.Table.from_pylist(value)
            return ArrowPayload(table)
        except Exception as exc:
            _log.debug("Arrow conversion from pylist failed: %s", exc)
            return value

    if isinstance(value, dict) and value and all(
        isinstance(column, (list, tuple)) for column in value.values()
    ):
        try:
            table = pa.Table.from_pydict(value)
            return ArrowPayload(table)
        except Exception as exc:
            _log.debug("Arrow conversion from pydict failed: %s", exc)
            return value

    return value


def _from_arrow_payload(value: Any) -> Any:
    if isinstance(value, ArrowPayload):
        return value.to_pylist()
    return value


def adapt_payload_for_child(payload: Any, producer: Any, child: Any) -> Any:
    """Adapt payload across node boundary with Arrow fallback semantics."""
    producer_arrow = bool(getattr(producer, "supports_arrow", False))
    child_arrow = bool(getattr(child, "supports_arrow", False))

    if producer_arrow and child_arrow:
        return _to_arrow_payload(payload)

    if isinstance(payload, ArrowPayload) and not child_arrow:
        return _from_arrow_payload(payload)

    return payload


def normalize_node_input(payload: Any, node: Any) -> Any:
    """Decode Arrow payload when the receiving node does not opt in."""
    node_arrow = bool(getattr(node, "supports_arrow", False))
    if isinstance(payload, ArrowPayload) and not node_arrow:
        return _from_arrow_payload(payload)
    return payload
