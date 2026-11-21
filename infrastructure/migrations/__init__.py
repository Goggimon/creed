from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from core.ports.memory import MigrationError, UnsupportedSchemaVersionError
from infrastructure.migrations.v001_legacy_baseline import upgrade as _v1_up
from infrastructure.migrations.v002_performance_indexes import upgrade as _v2_up
from infrastructure.migrations.v003_persistent_tasks import upgrade as _v3_up
from infrastructure.migrations.v004_task_security_and_leases import upgrade as _v4_up


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    up: Callable[[sqlite3.Connection], None]


DEFAULT_MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, description="baseline_legacy_schema", up=_v1_up),
    Migration(version=2, description="add_performance_indexes", up=_v2_up),
    Migration(version=3, description="add_persistent_tasks", up=_v3_up),
    Migration(version=4, description="add_task_security_and_leases", up=_v4_up),
)


class SQLiteMigrator:
    """Versioned, transactional SQLite schema migrator with pre-migration backup & verification."""

    def __init__(self, db_path: str, migrations: tuple[Migration, ...] | list[Migration] = DEFAULT_MIGRATIONS):
        self.db_path = db_path
        ordered = sorted(migrations, key=lambda m: m.version)
        seen: set[int] = set()
        for m in ordered:
            if m.version <= 0:
                raise MigrationError(f"Migration version must be positive, got {m.version}")
            if m.version in seen:
                raise MigrationError(f"Duplicate migration version: {m.version}")
            seen.add(m.version)
        self.migrations = tuple(ordered)
        self.latest_version = max((m.version for m in self.migrations), default=0)

    def _unique_backup_path(self) -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pid = os.getpid()
        seq = 0
        while True:
            suffix = f".bak.{stamp}.{pid}" if seq == 0 else f".bak.{stamp}.{pid}.{seq}"
            candidate = f"{self.db_path}{suffix}"
            if not os.path.exists(candidate):
                return candidate
            seq += 1

    def create_verified_backup(self) -> str:
        """Create a consistent SQLite backup using sqlite3.Connection.backup() and verify integrity."""
        backup_path = self._unique_backup_path()
        src = sqlite3.connect(self.db_path, timeout=30.0)
        dst = sqlite3.connect(backup_path, timeout=30.0)
        try:
            src.backup(dst)
            dst.commit()
        except sqlite3.Error as exc:
            dst.close()
            if os.path.exists(backup_path):
                try:
                    os.remove(backup_path)
                except OSError:
                    pass
            raise MigrationError(f"Failed to create SQLite backup: {exc}") from exc
        finally:
            try:
                dst.close()
            except Exception:
                pass
            src.close()

        verify = sqlite3.connect(backup_path, timeout=30.0)
        try:
            integrity = verify.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise MigrationError(f"Backup integrity check failed: {integrity}")
            verify.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        except sqlite3.Error as exc:
            raise MigrationError(f"Backup verification read failed: {exc}") from exc
        finally:
            verify.close()
        return backup_path

    def _restore_from_backup(self, backup_path: str) -> None:
        src = sqlite3.connect(backup_path, timeout=30.0)
        dst = sqlite3.connect(self.db_path, timeout=30.0)
        try:
            src.backup(dst)
            dst.commit()
        finally:
            dst.close()
            src.close()

    @staticmethod
    def get_current_version(conn: sqlite3.Connection) -> int:
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone()
        if not has_table:
            return 0
        row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()
        return int(row[0]) if row else 0

    def migrate(self) -> dict:
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        try:
            current_version = self.get_current_version(conn)
            if current_version > self.latest_version:
                raise UnsupportedSchemaVersionError(
                    f"Database schema version {current_version} is newer than supported version {self.latest_version}."
                )

            pending = [m for m in self.migrations if m.version > current_version]
            if not pending:
                return {"current_version": current_version, "applied": [], "backup_path": None}

            existing_tables = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchone()[0]
        finally:
            conn.close()

        backup_path = None
        if existing_tables > 0:
            backup_path = self.create_verified_backup()

        applied: list[int] = []
        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        try:
            for migration in pending:
                try:
                    conn.execute("BEGIN")
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS schema_version (
                            version INTEGER PRIMARY KEY,
                            description TEXT NOT NULL,
                            applied_at TEXT NOT NULL
                        )
                        """
                    )
                    migration.up(conn)
                    conn.execute(
                        "INSERT INTO schema_version (version, description, applied_at) VALUES (?, ?, ?)",
                        (migration.version, migration.description, datetime.now().isoformat()),
                    )
                    conn.execute("COMMIT")
                    applied.append(migration.version)
                except Exception as exc:
                    try:
                        conn.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                    conn.close()
                    if backup_path and applied:
                        self._restore_from_backup(backup_path)
                    err = MigrationError(
                        f"Migration v{migration.version} ({migration.description}) failed: {exc}"
                    )
                    err.backup_path = backup_path
                    raise err from exc
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return {
            "current_version": self.latest_version,
            "applied": applied,
            "backup_path": backup_path,
        }
