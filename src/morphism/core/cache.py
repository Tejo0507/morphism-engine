"""morphism.core.cache – Zero-latency SQLite functor cache (Phase 9).

Stores previously-verified lambda strings keyed by ``SHA-256(source::target)``
so the LLM + Z3 loop can be bypassed on subsequent identical mismatches.

The database is created lazily on first access at ``.morphism_cache.db``
in the current working directory.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Optional

from morphism.utils.logger import get_logger

_log = get_logger("core.cache")

_DB_PATH = Path(".morphism_cache.db")

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS functors (
    schema_hash  TEXT     PRIMARY KEY,
    source_name  TEXT     NOT NULL,
    target_name  TEXT     NOT NULL,
    lambda_string TEXT    NOT NULL,
    proof_certificate_path TEXT,
    timestamp    DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""


def _schema_hash(source_name: str, target_name: str) -> str:
    """SHA-256 of ``"{source_name}::{target_name}"``."""
    payload = f"{source_name}::{target_name}"
    return hashlib.sha256(payload.encode()).hexdigest()


class FunctorCache:
    """Thread-safe, lazy-init SQLite functor cache."""

    def __init__(self, db_path: Path | str = _DB_PATH) -> None:
        self._db_path = str(db_path)
        self._conn: Optional[sqlite3.Connection] = None

    # ── Lazy connection ──────────────────────────────────────────────

    def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, timeout=5)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(_CREATE_TABLE)
            self._ensure_columns(self._conn)
            self._conn.commit()
            _log.debug("Opened cache DB at %s", self._db_path)
        return self._conn

    def _ensure_columns(self, conn: sqlite3.Connection) -> None:
        with conn:
            cur = conn.execute("PRAGMA table_info(functors)")
            columns = {row[1] for row in cur.fetchall()}
            if "proof_certificate_path" not in columns:
                conn.execute(
                    "ALTER TABLE functors ADD COLUMN proof_certificate_path TEXT"
                )

    # ── Public API ───────────────────────────────────────────────────

    def lookup(self, source_name: str, target_name: str) -> Optional[str]:
        """Return the cached lambda string, or ``None`` on miss."""
        conn = self._ensure_conn()
        h = _schema_hash(source_name, target_name)
        with conn:
            cur = conn.execute(
                "SELECT lambda_string FROM functors WHERE schema_hash = ?",
                (h,),
            )
            row = cur.fetchone()
        if row is not None:
            _log.info(
                "[CACHE HIT] Bypassing AI for %s->%s",
                source_name, target_name,
            )
            return row[0]
        _log.debug(
            "[CACHE MISS] %s->%s (hash=%s)", source_name, target_name, h[:12],
        )
        return None

    def store(
        self,
        source_name: str,
        target_name: str,
        lambda_string: str,
        *,
        proof_certificate_path: str | None = None,
    ) -> None:
        """Insert (or replace) a verified lambda into the cache."""
        conn = self._ensure_conn()
        h = _schema_hash(source_name, target_name)
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO functors "
                "(schema_hash, source_name, target_name, lambda_string, proof_certificate_path) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    h,
                    source_name,
                    target_name,
                    lambda_string,
                    proof_certificate_path,
                ),
            )
        _log.info(
            "[CACHE STORE] %s->%s persisted (hash=%s…)",
            source_name, target_name, h[:12],
        )

    def delete(self, source_name: str, target_name: str) -> None:
        """Delete a cached mapping if present."""
        conn = self._ensure_conn()
        h = _schema_hash(source_name, target_name)
        with conn:
            conn.execute(
                "DELETE FROM functors WHERE schema_hash = ?",
                (h,),
            )
        _log.info(
            "[CACHE DELETE] %s->%s removed (hash=%s…)",
            source_name, target_name, h[:12],
        )

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # Context-manager support
    def __enter__(self) -> "FunctorCache":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
