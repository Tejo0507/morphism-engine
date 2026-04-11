"""morphism.core.inference – Dynamic schema inference from data streams.

Inspects raw textual output from native OS commands and returns the
best-matching :class:`~morphism.core.schemas.Schema`.
"""

from __future__ import annotations

import csv
import json

from morphism.core.schemas import CSV_Data, JSON_Object, Plaintext, Schema
from morphism.utils.logger import get_logger

_log = get_logger("core.inference")


def infer_schema(data: str) -> Schema:
    """Return the most specific :class:`Schema` matching *data*.

    Heuristics (applied in order of specificity):

    1. Valid JSON object or array → :data:`JSON_Object`
    2. Two or more lines with a consistent CSV dialect → :data:`CSV_Data`
    3. Everything else (including empty strings) → :data:`Plaintext`
    """
    stripped = data.strip()

    if not stripped:
        _log.debug("Empty data → Plaintext")
        return Plaintext

    # ── 1. JSON ──────────────────────────────────────────────────────
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, (dict, list)):
            _log.debug(
                "Detected JSON_Object (Python type=%s)", type(parsed).__name__,
            )
            return JSON_Object
    except (json.JSONDecodeError, ValueError):
        pass

    # ── 2. CSV ───────────────────────────────────────────────────────
    lines = stripped.splitlines()
    if len(lines) >= 2:
        try:
            dialect = csv.Sniffer().sniff(stripped[:4096])
            # Only accept common CSV delimiters to avoid false positives
            # (the Sniffer sometimes picks up spaces or other characters).
            if dialect.delimiter in (",", "\t", ";", "|"):
                _log.debug(
                    "Detected CSV_Data (%d lines, delim=%r)",
                    len(lines), dialect.delimiter,
                )
                return CSV_Data
        except csv.Error:
            pass

    # ── 3. Fallback ──────────────────────────────────────────────────
    _log.debug("Fallback → Plaintext")
    return Plaintext
