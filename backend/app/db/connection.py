"""SQLite database connection and lifecycle management with WAL mode."""

import os
import sqlite3
from typing import Generator
from pathlib import Path

try:
    os.umask(0)
except Exception:
    pass


def get_db_path() -> str:
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    default_path = str(repo_root / "data" / "checkout_radar.db")
    db_env = os.getenv("SQLITE_DB_PATH", default_path)
    if db_env.startswith("/app/") and not Path("/app").exists():
        db_env = str(repo_root / "data" / Path(db_env).name)
    path = Path(db_env)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def get_connection() -> sqlite3.Connection:
    """Return a configured SQLite connection with foreign keys and Row factory."""
    conn = sqlite3.connect(get_db_path(), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    return conn


def seed_demo_data_if_empty(conn: sqlite3.Connection):
    """If database has no audits, seed baseline demo audits from data/demo_seed.json."""
    cursor = conn.cursor()
    count = cursor.execute("SELECT COUNT(*) FROM audits").fetchone()[0]
    if count > 0:
        return
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    seed_path = repo_root / "data" / "demo_seed.json"
    if not seed_path.exists():
        # Check /app/data/demo_seed.json for container environment
        seed_path = Path("/app/data/demo_seed.json")
    if not seed_path.exists():
        return

    import json
    with open(seed_path, "r", encoding="utf-8") as f:
        seed_data = json.load(f)

    tables = [
        "audits", "conditions", "runs", "jobs", "snapshots",
        "stage_captures", "charge_observations", "disclosure_observations",
        "urgency_observations", "diffs", "findings", "provider_calls"
    ]
    for table in tables:
        rows = seed_data.get(table, [])
        for row in rows:
            cols = list(row.keys())
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            sql = f"INSERT OR IGNORE INTO {table} ({col_names}) VALUES ({placeholders})"
            cursor.execute(sql, [row[c] for c in cols])
    conn.commit()


def init_db(seed_demo: bool = True):
    """Initialize database tables from schema.sql."""
    schema_path = Path(__file__).parent / "schema.sql"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    conn = get_connection()
    try:
        conn.executescript(schema_sql)
        cols = [c["name"] for c in conn.execute("PRAGMA table_info(findings)").fetchall()]
        if "raw_observations" not in cols:
            conn.execute("ALTER TABLE findings ADD COLUMN raw_observations TEXT DEFAULT NULL;")
        job_cols = [c["name"] for c in conn.execute("PRAGMA table_info(jobs)").fetchall()]
        if "lease_generation" not in job_cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN lease_generation INTEGER NOT NULL DEFAULT 0;")
        conn.commit()

        # Seed baseline demo fixtures on fresh clone if audits table is empty and not running unit tests
        if seed_demo and not os.getenv("PYTEST_CURRENT_TEST"):
            seed_demo_data_if_empty(conn)
    finally:
        conn.close()
