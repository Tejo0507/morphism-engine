"""morphism.utils.logger – Centralised logging configuration.

Console handler:  clean ``[LEVEL] message`` at INFO level.
File handler:     full ``timestamp [LEVEL] name – message`` at DEBUG level,
                  written to ``logs/morphism.log``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path


_CONFIGURED = False


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with console + rotating file handlers.

    Safe to call multiple times – subsequent calls are no-ops.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    root = logging.getLogger("morphism")
    root.setLevel(logging.DEBUG)
    root.propagate = False

    # ── Console handler (INFO+) ──────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(getattr(logging, level.upper(), logging.INFO))
    console.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    root.addHandler(console)

    # ── File handler (DEBUG) ─────────────────────────────────────────
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    fh = logging.FileHandler(log_dir / "morphism.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s – %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(fh)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the ``morphism`` namespace."""
    return logging.getLogger(f"morphism.{name}")
