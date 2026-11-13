"""Compare two builds of the dataset, e.g. before and after a new catalog edition.

For every table in either database: row counts, and rows added or removed (whole rows compared, so a changed
value shows as one removed and one added row). Prints Markdown; samples of changed rows are included.

Usage:
    cp data/fisher.db /tmp/old.db      # before re-running `make data` on the new edition
    make data
    python extract/diff_dataset.py /tmp/old.db data/fisher.db [--samples 5] > docs/edition_diff.md
"""
from __future__ import annotations

import argparse
import sqlite3

SKIP = {"dataset_info", "build_input"}  # build metadata changes every time


def tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def rows(con: sqlite3.Connection, table: str) -> tuple[list[str], set[tuple]]:
    cur = con.execute(f'SELECT * FROM "{table}"')
    return [d[0] for d in cur.description], set(cur.fetchall())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--samples", type=int, default=5)
    args = ap.parse_args()
    old, new = sqlite3.connect(f"file:{args.old}?mode=ro", uri=True), sqlite3.connect(f"file:{args.new}?mode=ro", uri=True)
    info = {}
    for name, con in (("old", old), ("new", new)):
        if "dataset_info" in tables(con):
            info[name] = dict(con.execute("SELECT key, value FROM dataset_info"))
    print(f"# Dataset diff\n\n- old: {args.old} {info.get('old', {}).get('version', '')}"
          f"\n- new: {args.new} {info.get('new', {}).get('version', '')}\n")
    for k in ("catalog12_sha256", "catalog14_sha256"):
        a, b = info.get("old", {}).get(k), info.get("new", {}).get(k)
        if a and b and a != b:
            print(f"- **{k} changed**: a different catalog edition\n")
    print("| table | old rows | new rows | removed | added |\n|---|---|---|---|---|")
    details = []
    for t in sorted((tables(old) | tables(new)) - SKIP):
        if t not in tables(old) or t not in tables(new):
            print(f"| {t} | {'-' if t not in tables(old) else 'present'} | {'-' if t not in tables(new) else 'present'} | | |")
            continue
        cols_o, ro = rows(old, t)
        cols_n, rn = rows(new, t)
        if cols_o != cols_n:
            print(f"| {t} | {len(ro)} | {len(rn)} | columns changed | |")
            continue
        removed, added = ro - rn, rn - ro
        print(f"| {t} | {len(ro)} | {len(rn)} | {len(removed)} | {len(added)} |")
        if removed or added:
            details.append((t, cols_o, sorted(removed, key=str)[:args.samples], sorted(added, key=str)[:args.samples]))
    for t, cols, removed, added in details:
        print(f"\n## {t}\n\ncolumns: {', '.join(cols)}\n")
        for label, rs in (("removed", removed), ("added", added)):
            for r in rs:
                print(f"- {label}: {r}")


if __name__ == "__main__":
    main()
