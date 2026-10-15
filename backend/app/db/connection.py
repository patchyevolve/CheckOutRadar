"""SQLite database connection and lifecycle management with WAL mode."""

import os
import sqlite3
from typing import Generator
from pathlib import Path

def get_db_path() -> str:
    db_env = os.getenv("SQLITE_DB_PATH", "/home/daksh/working/checkout-radar/data/checkout_radar.db")
    if db_env.startswith("/app/") and not Path("/app").exists():
        db_env = str(Path(__file__).resolve().parent.parent.parent.parent / "data" / Path(db_env).name)
    path = Path(db_env)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def get_connection() -> sqlite3.Connection:
    """Return a configured SQLite connection with foreign keys and Row factory."""
    conn = sqlite3.connect(get_db_path(), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db():
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
        conn.commit()
    finally:
        conn.close()
