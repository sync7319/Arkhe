"""
SQLite-backed per-file cache for Arkhe.

Stores AST structure and LLM analysis keyed by (file_path, content_hash).
A cache entry is valid as long as the file's content hasn't changed — regardless
of what else changed in the repo. A 1-file change in a 200-file repo triggers
1 LLM call, not 200.

DB lives at <repo>/.arkhe_cache/arkhe.db — one file, no server, zero cost.
Schema is forward-compatible with Postgres (no SQLite-isms in the data model).
"""
import hashlib
import json
import logging
import sqlite3
import threading
from datetime import date
from pathlib import Path

logger = logging.getLogger("arkhe.db")

_instance: "ArkheDB | None" = None


class ArkheDB:
    def __init__(self, repo_path: str):
        db_dir = Path(repo_path) / ".arkhe_cache"
        db_dir.mkdir(exist_ok=True)
        self._conn = sqlite3.connect(str(db_dir / "arkhe.db"), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS file_cache (
                file_path    TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                tokens       INTEGER,
                structure    TEXT,
                analysis     TEXT,
                PRIMARY KEY (file_path, content_hash)
            );

            -- Persisted model cooldowns so rate-limited models stay cooling
            -- across process restarts (not just within a single run).
            CREATE TABLE IF NOT EXISTS model_cooldowns (
                model      TEXT PRIMARY KEY,
                cool_until REAL NOT NULL
            );

            -- Tracks the last date cooldowns were reset, enabling the daily
            -- fresh-start behaviour (first run of each day clears all cooldowns).
            CREATE TABLE IF NOT EXISTS run_metadata (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        self._conn.commit()

    @staticmethod
    def content_hash(content: str) -> str:
        """SHA-1 of file content — cache key for a specific version of a file."""
        return hashlib.sha1(content.encode()).hexdigest()

    # ── reads ──────────────────────────────────────────────────────────────────

    def get_file(self, file_path: str, content_hash: str) -> "dict | None":
        """Return cached data for a file version, or None on miss."""
        with self._lock:
            row = self._conn.execute(
                "SELECT tokens, structure, analysis FROM file_cache "
                "WHERE file_path=? AND content_hash=?",
                (file_path, content_hash),
            ).fetchone()
        if row is None:
            return None
        structure = None
        if row["structure"]:
            try:
                structure = json.loads(row["structure"])
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"[cache] corrupt structure for {file_path} — will re-parse ({e})")
        return {
            "tokens":    row["tokens"],
            "structure": structure,
            "analysis":  row["analysis"],
        }

    # ── writes ─────────────────────────────────────────────────────────────────

    def save_structure(
        self, file_path: str, content_hash: str, tokens: int, structure: dict
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO file_cache (file_path, content_hash, tokens, structure)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(file_path, content_hash) DO UPDATE SET
                       tokens=excluded.tokens, structure=excluded.structure""",
                (file_path, content_hash, tokens, json.dumps(structure)),
            )
            self._conn.commit()

    def save_analysis(self, file_path: str, content_hash: str, analysis: str) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO file_cache (file_path, content_hash, analysis)
                   VALUES (?, ?, ?)
                   ON CONFLICT(file_path, content_hash) DO UPDATE SET
                       analysis=excluded.analysis""",
                (file_path, content_hash, analysis),
            )
            self._conn.commit()

    # ── model cooldowns ────────────────────────────────────────────────────────

    def set_cooling(self, model: str, cool_until: float) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO model_cooldowns (model, cool_until) VALUES (?, ?) "
                "ON CONFLICT(model) DO UPDATE SET cool_until=excluded.cool_until",
                (model, cool_until),
            )
            self._conn.commit()

    def get_all_cooldowns(self) -> list[tuple[str, float]]:
        """Return [(model, cool_until), ...] for all persisted cooldowns."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT model, cool_until FROM model_cooldowns"
            ).fetchall()
        return [(r["model"], r["cool_until"]) for r in rows]

    def clear_cooldowns(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM model_cooldowns")
            self._conn.commit()

    def reset_daily_if_needed(self) -> bool:
        """
        If today's date differs from the stored last-reset date, clear all
        model cooldowns and update the stored date. Returns True if reset ran.
        This gives every chain a fresh start at the beginning of each day.
        """
        today = str(date.today())
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM run_metadata WHERE key='last_reset_date'"
            ).fetchone()
            last = row["value"] if row else None

            if last == today:
                return False

            # New day — wipe cooldowns and record today
            self._conn.execute("DELETE FROM model_cooldowns")
            self._conn.execute(
                "INSERT INTO run_metadata (key, value) VALUES ('last_reset_date', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (today,),
            )
            self._conn.commit()
        return True

    def close(self) -> None:
        self._conn.close()


def init_db(repo_path: str) -> ArkheDB:
    """Initialize the singleton DB for this run. Call once from main.py."""
    global _instance
    _instance = ArkheDB(repo_path)
    return _instance


def get_db() -> ArkheDB:
    """Return the initialized DB. Raises if init_db() was not called first."""
    if _instance is None:
        raise RuntimeError("ArkheDB not initialized — call init_db(repo_path) first.")
    return _instance
