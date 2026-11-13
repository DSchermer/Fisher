"""Read-only access to the unified dataset, data/fisher.db (see docs/DATA_MODEL.md)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "fisher.db"


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open the database read-only. Rows behave like dicts (sqlite3.Row)."""
    con = sqlite3.connect(f"file:{Path(path or DB_PATH).as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def query(sql: str, params: tuple | dict = (), path: str | Path | None = None) -> list[dict]:
    """Run a read-only query and return a list of dicts."""
    con = connect(path)
    try:
        return [dict(r) for r in con.execute(sql, params)]
    finally:
        con.close()
