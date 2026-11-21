# CREED Memory Repository & SQLite Migration Guide

## 1. Architecture & Boundary
- **Domain & Retrieval (`modules/memory.py`)**: Defines `MemoryRepository` (`Protocol`), domain errors (`MemoryError`, `MigrationError`, `UnsupportedSchemaVersionError`), `InMemoryMemoryRepository`, and `Module`. It has zero `sqlite3` imports and receives its repository via dependency injection.
- **SQLite Adapter & Migrator (`core/router.py`)**: Implements `SQLiteMemoryRepository` and `SQLiteMigrator`, constructed and injected by `build_creed_engine()`. All `sqlite3.Error` exceptions are wrapped into `MemoryError`, and all results are returned as plain Python dicts/lists.

## 2. Schema Versioning (`schema_version`)
`SQLiteMigrator` uses a dedicated `schema_version` table as the authoritative version store:

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
```

- **Legacy Unversioned Databases (`version = 0`)**: Databases created before Tranche 4 have the 7 core tables (`notes`, `reminders`, `conversations`, `messages`, `workflows`, `jee_flashcards`, `jee_tests`) without `schema_version`.
- **Migration v1 (`baseline_legacy_schema`)**: Uses `CREATE TABLE IF NOT EXISTS` and `INSERT OR IGNORE` for `'default'` conversation, preserving all existing rows, primary key IDs, timestamps, metadata, and relationships.
- **Migration v2 (`add_performance_indexes`)**: Adds non-destructive indexes on `messages(session_id)`, `reminders(time)`, `jee_flashcards(subject)`, and `notes(tag)`.
- **Migration v3 (`add_persistent_tasks`)**: Adds `tasks`, `task_checkpoints`, `task_events`, and `task_approvals` tables (with status/task/conversation indexes) for persistent task orchestration and restart recovery.
- **Future Schema Guard**: If `schema_version` contains a version higher than the application's `latest_version`, `SQLiteMigrator.migrate()` raises `UnsupportedSchemaVersionError` immediately without modifying or backing up the database.
- **Idempotency**: Only migrations with `version > current_version` are executed; repeated runs are no-ops.

## 3. Pre-Migration Backup & Recovery Procedure
Before applying pending migrations to an existing database with tables:
1. `SQLiteMigrator.create_verified_backup()` generates a unique timestamped path (`<db_path>.bak.<YYYYMMDD_HHMMSS>.<pid>[.<seq>]`) so existing backups are never overwritten.
2. It uses SQLite's online backup API (`sqlite3.Connection.backup()`) rather than raw file copying, ensuring consistent snapshots even in `WAL` mode.
3. It verifies the backup by opening it and running `PRAGMA integrity_check` (`"ok"`) and `SELECT COUNT(*) FROM sqlite_master` before touching the live database.
4. Each migration executes inside an explicit transaction (`BEGIN` / `COMMIT` / `ROLLBACK`). If any migration fails, the transaction is rolled back, any earlier migrations in that batch are reverted from the verified backup, and `MigrationError` is raised with `.backup_path` preserved.

### Manual Recovery Steps
If a migration fails or you need to revert `creed.db` to a pre-migration snapshot:
1. Stop CREED (`api/server.py` / desktop GUI) so no connections hold locks on `creed.db`.
2. Verify the backup file's integrity:
   ```bash
   sqlite3 /path/to/creed.db.bak.<timestamp>.<pid> "PRAGMA integrity_check;"
   ```
3. Restore the backup using SQLite's `.backup` command (safe for WAL files) or by removing stale `-wal`/`-shm` sidecars after stopping CREED and copying the verified `.bak` file over `creed.db`:
   ```bash
   rm -f /path/to/creed.db-wal /path/to/creed.db-shm
   cp /path/to/creed.db.bak.<timestamp>.<pid> /path/to/creed.db
   ```
4. Restart CREED and verify notes, conversations, and flashcards are intact.
