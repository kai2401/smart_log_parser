"""
Database layer: SQLite storage for parsed LogEntry and RecipeEntry records.
"""

import sqlite3
import json
from typing import Any
from parser.schema import LogEntry, RecipeEntry
import config

CREATE_LOG_SQL = """
CREATE TABLE IF NOT EXISTS log_entries (
    id                  TEXT PRIMARY KEY,
    timestamp           TEXT,
    tool_id             TEXT,
    log_type            TEXT,
    severity            TEXT,
    raw_message         TEXT,
    drain_cluster_id    INTEGER,
    metadata            TEXT,
    source_format       TEXT,
    source_filename     TEXT,
    ai_summary          TEXT,
    ai_classification   TEXT,
    ai_root_cause_hint  TEXT
);
"""

CREATE_RECIPE_SQL = """
CREATE TABLE IF NOT EXISTS recipe_entries (
    id                  TEXT PRIMARY KEY,
    timestamp           TEXT,
    tool_id             TEXT,
    metadata            TEXT,
    raw_message         TEXT,
    source_format       TEXT,
    source_filename     TEXT
);
"""

CREATE_JOBS_SQL = """
CREATE TABLE IF NOT EXISTS processing_jobs (
    id              TEXT PRIMARY KEY,
    filename        TEXT NOT NULL,
    status          TEXT NOT NULL,
    progress        INTEGER NOT NULL,
    error_message   TEXT,
    total_records   INTEGER
);
"""

INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_timestamp  ON log_entries(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_tool_id    ON log_entries(tool_id);",
    "CREATE INDEX IF NOT EXISTS idx_severity   ON log_entries(severity);",
    "CREATE INDEX IF NOT EXISTS idx_recipe_tool ON recipe_entries(tool_id);",
]


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _get_conn() as conn:
        conn.execute(CREATE_LOG_SQL)
        conn.execute(CREATE_RECIPE_SQL)
        conn.execute(CREATE_JOBS_SQL)
        _ensure_column(conn, "log_entries", "metadata", "TEXT")
        for idx in INDEX_SQL:
            conn.execute(idx)
        conn.commit()


def _ensure_column(
    conn: sqlite3.Connection, table: str, column: str, col_type: str
) -> None:
    existing = {
        row["name"] for row in conn.execute(f"PRAGMA table_info({table})")
    }
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def insert_entries(entries: list[LogEntry]) -> int:
    """Insert a batch of log entries. Returns count inserted."""
    if not entries:
        return 0

    cols = [f for f in LogEntry.__dataclass_fields__]
    placeholders = ", ".join("?" * len(cols))
    sql = (
        f"INSERT OR IGNORE INTO log_entries ({', '.join(cols)}) VALUES ({placeholders})"
    )

    rows = []
    for e in entries:
        d = e.to_dict()
        rows.append(tuple(d.get(c) for c in cols))

    with _get_conn() as conn:
        conn.executemany(sql, rows)
        conn.commit()
    return len(rows)


def insert_recipes(entries: list[RecipeEntry]) -> int:
    """Insert a batch of recipe entries. Returns count inserted."""
    if not entries:
        return 0

    cols = [f for f in RecipeEntry.__dataclass_fields__]
    placeholders = ", ".join("?" * len(cols))
    sql = (
        f"INSERT OR IGNORE INTO recipe_entries ({', '.join(cols)}) VALUES ({placeholders})"
    )

    rows = []
    for e in entries:
        d = e.to_dict()
        rows.append(tuple(d.get(c) for c in cols))

    with _get_conn() as conn:
        conn.executemany(sql, rows)
        conn.commit()
    return len(rows)


def update_ai_fields(
    entry_id: str, summary: str, classification: str, hint: str
) -> None:
    sql = """
    UPDATE log_entries
    SET ai_summary = ?, ai_classification = ?, ai_root_cause_hint = ?
    WHERE id = ?
    """
    with _get_conn() as conn:
        conn.execute(sql, (summary, classification, hint, entry_id))
        conn.commit()


def query_entries(
    tool_id: str | None = None,
    severity: str | None = None,
    log_type: str | None = None,
    start_ts: str | None = None,
    end_ts: str | None = None,
    search: str | None = None,
    source_filename: str | None = None,
    limit: int = 1000,
) -> list[dict]:
    conditions = []
    params: list[Any] = []

    if tool_id:
        conditions.append("tool_id = ?")
        params.append(tool_id)
    if severity:
        conditions.append("severity = ?")
        params.append(severity)
    if log_type:
        conditions.append("log_type = ?")
        params.append(log_type)
    if start_ts:
        conditions.append("timestamp >= ?")
        params.append(start_ts)
    if end_ts:
        conditions.append("timestamp <= ?")
        params.append(end_ts)
    if source_filename:
        conditions.append("source_filename = ?")
        params.append(source_filename)
    if search:
        conditions.append(
            "(raw_message LIKE ? OR json_extract(metadata, '$.event_name') LIKE ? OR json_extract(metadata, '$.normalized_message') LIKE ?)"
        )
        pattern = f"%{search}%"
        params.extend([pattern, pattern, pattern])

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = (
        f"SELECT * FROM log_entries {where} ORDER BY timestamp DESC, rowid DESC LIMIT ?"
    )
    params.append(limit)

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        
    results = []
    for r in rows:
        d = dict(r)
        if d.get("metadata"):
            try:
                meta = json.loads(d.pop("metadata"))
                d.update(meta)
            except Exception:
                pass
        results.append(d)
    return results


def query_recipes(
    tool_id: str | None = None,
    recipe_id: str | None = None,
    source_filename: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """Query recipe entries with optional filters."""
    conditions = []
    params: list[Any] = []

    if tool_id:
        conditions.append("tool_id = ?")
        params.append(tool_id)
    if recipe_id:
        conditions.append("json_extract(metadata, '$.recipe_id') = ?")
        params.append(recipe_id)
    if source_filename:
        conditions.append("source_filename = ?")
        params.append(source_filename)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT * FROM recipe_entries {where} ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    results = []
    for r in rows:
        d = dict(r)
        if d.get("metadata"):
            try:
                meta = json.loads(d.pop("metadata"))
                d.update(meta)
            except Exception:
                pass
        results.append(d)
    return results


def get_summary_stats(source_filename: str | None = None) -> dict:
    where = "WHERE source_filename = ?" if source_filename else ""
    params = [source_filename] if source_filename else []

    with _get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM log_entries {where}", params
        ).fetchone()[0]
        alarms = conn.execute(
            f"SELECT COUNT(*) FROM log_entries {where} {'AND' if where else 'WHERE'} log_type = 'alarm'",
            params,
        ).fetchone()[0]
        errors = conn.execute(
            f"SELECT COUNT(*) FROM log_entries {where} {'AND' if where else 'WHERE'} severity IN ('ERROR','CRITICAL')",
            params,
        ).fetchone()[0]
        warnings_c = conn.execute(
            f"SELECT COUNT(*) FROM log_entries {where} {'AND' if where else 'WHERE'} severity = 'WARNING'",
            params,
        ).fetchone()[0]
        tools = conn.execute(
            f"SELECT COUNT(DISTINCT tool_id) FROM log_entries {where}", params
        ).fetchone()[0]
        recipes = conn.execute(
            f"SELECT COUNT(*) FROM recipe_entries {'WHERE source_filename = ?' if source_filename else ''}",
            [source_filename] if source_filename else [],
        ).fetchone()[0]
    return {
        "total": total,
        "alarms": alarms,
        "errors": errors,
        "warnings": warnings_c,
        "tools": tools,
        "recipes": recipes,
    }


def get_distinct_values(column: str, source_filename: str | None = None) -> list[str]:
    where = "WHERE source_filename = ?" if source_filename else ""
    params = [source_filename] if source_filename else []
    
    # If it's a dynamic column, extract from JSON
    core_columns = {"id", "timestamp", "tool_id", "log_type", "severity", "raw_message", "drain_cluster_id", "source_format", "source_filename", "ai_summary", "ai_classification", "ai_root_cause_hint", "metadata"}
    if column not in core_columns:
        db_col = f"json_extract(metadata, '$.{column}')"
    else:
        db_col = column

    with _get_conn() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT {db_col} FROM log_entries {where} ORDER BY {db_col}",
            params,
        ).fetchall()
    return [r[0] for r in rows if r[0]]


def clear_all() -> None:
    with _get_conn() as conn:
        conn.execute("DELETE FROM log_entries")
        conn.execute("DELETE FROM recipe_entries")
        conn.commit()


def delete_by_filename(filename: str) -> None:
    with _get_conn() as conn:
        conn.execute("DELETE FROM log_entries WHERE source_filename = ?", (filename,))
        conn.execute("DELETE FROM recipe_entries WHERE source_filename = ?", (filename,))
        conn.commit()


def create_job(job_id: str, filename: str) -> None:
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO processing_jobs (id, filename, status, progress) VALUES (?, ?, ?, ?)",
            (job_id, filename, "PENDING", 0),
        )
        conn.commit()


def update_job(
    job_id: str,
    status: str,
    progress: int,
    error_message: str | None = None,
    total_records: int | None = None,
) -> None:
    with _get_conn() as conn:
        conn.execute(
            """
            UPDATE processing_jobs
            SET status = ?, progress = ?, error_message = ?, total_records = ?
            WHERE id = ?
            """,
            (status, progress, error_message, total_records, job_id),
        )
        conn.commit()


def get_job(job_id: str) -> dict | None:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id, filename, status, progress, error_message, total_records FROM processing_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    return dict(row) if row else None

