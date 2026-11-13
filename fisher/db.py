"""Read-only access to the unified dataset, data/fisher.db (see docs/DATA_MODEL.md).

The database is not stored in git: it is built from the CSV files under data/ (about 15 seconds, no PDFs
needed) the first time it is used, and rebuilt whenever a CSV has changed since the last build (the build
records each CSV's SHA-256 in build_input).
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "fisher.db"
_checked: set[str] = set()


def _csv_hashes() -> dict[str, str]:
    return {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted((ROOT / "data").rglob("*.csv")) if "source" not in f.parts}


def is_current(path: Path = DB_PATH) -> bool:
    """True if the database exists and was built from the CSVs as they are now."""
    if not path.exists():
        return False
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            recorded = dict(con.execute("SELECT path, sha256 FROM build_input"))
        finally:
            con.close()
    except sqlite3.Error:
        return False
    return recorded == _csv_hashes()


def build(path: Path = DB_PATH) -> None:
    """Build the database from the CSVs (extract/build_db.py), atomically."""
    spec = importlib.util.spec_from_file_location("fisher_build_db", ROOT / "extract" / "build_db.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fd, tmp = tempfile.mkstemp(suffix=".db", dir=path.parent)
    os.close(fd)
    os.unlink(tmp)
    stdout, sys.stdout = sys.stdout, sys.stderr  # keep the build report off stdout (the MCP server uses it)
    try:
        mod.build(tmp, str(ROOT / "docs" / "DATA_MODEL.md"))
    finally:
        sys.stdout = stdout
    os.replace(tmp, path)


def ensure(path: Path = DB_PATH) -> None:
    """Build or rebuild the database if it is missing or older than the CSVs (checked once per process)."""
    key = str(path)
    if key in _checked:
        return
    if path == DB_PATH and not is_current(path):
        print("building data/fisher.db from the CSV files (about 15 seconds, once)...", file=sys.stderr)
        build(path)
    _checked.add(key)


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open the database read-only. Rows behave like dicts (sqlite3.Row)."""
    p = Path(path or DB_PATH)
    ensure(p)
    con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def query(sql: str, params: tuple | dict = (), path: str | Path | None = None) -> list[dict]:
    """Run a read-only query and return a list of dicts."""
    con = connect(path)
    try:
        return [dict(r) for r in con.execute(sql, params)]
    finally:
        con.close()
