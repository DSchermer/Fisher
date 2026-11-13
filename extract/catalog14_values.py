"""Typed values for every Catalog 14 table in the force method (section B) and torque method (section D).

The same treatment sections A and C get in catalog14_dp.py, generalized for the more varied B and D
layouts:
  - header rows are the gray-shaded rows (Catalog 14 shades every header row and row-group label);
    a shaded block after data starts a new header for the rows below it;
  - a row whose only text spans the table is a row-group label, e.g. "1.5 Inch Port";
  - key columns: the first column, columns whose header names a key (size, shaft, bearing, ...),
    and columns holding text (part numbers, materials); merged key cells are carried down;
  - every other cell is a value, with its full column header path;
  - figure grids that pdfplumber reads as tables (no header, no title) are skipped;
  - second reader: a row's values, in order, on one line of poppler's text ("line"), or for layouts that
    centre or merge cells vertically, all present within four consecutive lines ("window").

Writes data/catalog14/table_values.csv, and table_values_text_only.csv listing the tables with no numeric
values (they stay available as printed in data/catalog14/tables/).

Usage:
    python extract/catalog14_values.py data/source/d103428x012.pdf data/catalog14
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog14_dp import NUM, page_lines  # noqa: E402
from catalog14_force import split_rows  # noqa: E402
from catalog14_tables import page_heading, printed_label  # noqa: E402
from parse_tables import TABLE_SETTINGS, gray_rects, parse_value, shaded_fraction  # noqa: E402

KEY_HEADER = re.compile(
    r"size|nps|\bdn\b|shaft|bearing|seal|material|spring|part\s*(no|number)|travel|stroke|stem|port\b|"
    r"port\s*dia|class|rating|construction|design|type|style|trim|valve|actuator|cylinder|yoke|packing|"
    r"description|model|air\s*to|supply|signal|rotation|angle|temperature|disk|liner|flow|service|ring", re.I)
DASH = re.compile(r"^[-‐–\s]+$|^N/?A$|^---$|^CF$|^NR$")  # placeholders: none, not applicable, consult factory
UNIT_ONLY = re.compile(r"^\(?(inch(es)?|in\.?|lbf?(/inch|/in)?|lbf?[-‐]in(ch)?|psig?|psid|bar|barg|mm|n|n[-‐·]?m|kg|"
                       r"sq\.?\s*in(ch(es)?)?|in2|cm2|deg(rees)?|°[cf]?|%)\)?$", re.I)
VALUE_HEADER = re.compile(r"circumference|area|force|torque|friction|load|rate|preload|thrust|pressure drop|"
                          r"ΔP|percent|factor|\bT[bBdD]\b|weight|effective", re.I)


def is_number(x: str) -> bool:
    return parse_value(x)[0] is not None


ANNOTATED = re.compile(r"^(-?[\d,]*\.?\d+)\s*\n?\s*\(([^)]*[^\d)][^)]*)\)$")  # "207 (3-15)": a value and its note


def first_line(x: str) -> str:
    m = ANNOTATED.match(x.strip())
    return m.group(1) if m else x.split("\n")[0].strip()


def is_valueish(x: str) -> bool:
    """A number or placeholder; a number with a parenthesised note below it (e.g. "207\n(3-15)") counts."""
    return bool(x) and (is_number(x) or bool(DASH.match(x)) or (first_line(x) != x and is_number(first_line(x))))


def expand(raw, shade):
    """split_rows with the shaded flag and source row kept for each expanded row."""
    rows, flags = [], []
    for r, s in zip(raw, shade):
        sub = split_rows([r])
        rows += sub
        flags += [s] * len(sub)
    return rows, flags


def key_columns(header: list[list[str]], body: list[list[str]], ncols: int) -> list[int]:
    keys = [0]
    leading = True
    for c in range(1, ncols):
        own = [r[c] for r in header if r[c] and not UNIT_ONLY.match(r[c])]
        head = own[-1] if own else ""  # the column's own label, not the group headers above it
        cells = [r[c] for r in body if r[c]]
        text_cells = [x for x in cells if not is_valueish(x)]
        named_key = bool(KEY_HEADER.search(head)) and not VALUE_HEADER.search(" ".join(r[c] for r in header))
        if cells and len(text_cells) > len(cells) / 2:
            keys.append(c)  # a text column: materials, part numbers, descriptions
        elif leading and c == keys[-1] + 1 and (named_key or (KEY_HEADER.search(head)
                                                               and len(cells) < 0.9 * max(len(body), 1))):
            keys.append(c)  # a leading column named like a key (size, class, stem ...), or a sparse merged one
        else:
            leading = False
    return keys


def key_label(header: list[list[str]], c: int) -> str:
    """A key column's name: its own label, or the label to its left that spans it, with any unit below."""
    unit = next((h[c] for h in reversed(header) if h[c] and UNIT_ONLY.match(h[c])), "")
    label = next((h[c] for h in reversed(header) if h[c] and not UNIT_ONLY.match(h[c])), "")
    if not label and unit:
        for h in reversed(header):
            if not h[c]:
                label = next((h[j] for j in range(c - 1, -1, -1) if h[j]), "")
                if label and not UNIT_ONLY.match(label):
                    break
                label = ""
    return f"{label} ({unit})" if label and unit else label


def column_paths(header: list[list[str]], ncols: int, keys: list[int]) -> list[str]:
    rows = [list(r) for r in header]
    for r in rows:  # group headers spread right over the empty cells they span (value region only)
        for c in range(1, ncols):
            if not r[c] and r[c - 1] and c not in keys and (c - 1) not in keys:
                r[c] = r[c - 1]
    out = []
    for c in range(ncols):
        parts = []
        for r in rows:
            if r[c] and r[c] not in parts:
                parts.append(r[c])
        out.append(" › ".join(parts))
    return out


def convert(cells: list[list[str]], shaded: list[bool]):
    ncols = len(cells[0])
    data_idx = [i for i, r in enumerate(cells) if not shaded[i] and sum(1 for x in r[1:] if is_valueish(x)) >= 1
                and len({x for x in r if x}) > 1]
    if not data_idx:
        return []
    body = [cells[i] for i in data_idx]
    header_first = [cells[i] for i in range(data_idx[0]) if shaded[i] and sum(1 for x in cells[i] if x) > 1]
    keys = key_columns(header_first, body, ncols)
    key_names = {}
    records, header, group, current, row_no = [], header_first, "", {}, 0
    paths = column_paths(header, ncols, keys)
    in_header_block = False
    for i, r in enumerate(cells):
        texts = [x for x in r if x]
        if not texts:
            continue
        if len(texts) == 1 and not is_number(texts[0]):
            if not re.match(r"^\d+\.\s", texts[0]) and not texts[0].lower().startswith("note"):
                group = texts[0]
            continue
        if i < data_idx[0]:
            continue
        if shaded[i]:  # a header block restarting below data
            header = [r] if not in_header_block else header + [r]
            in_header_block = True
            paths = column_paths(header, ncols, keys)
            continue
        if i not in data_idx:
            continue
        in_header_block = False
        row_no += 1
        for c in keys:
            if r[c]:
                current[c] = r[c]
        for c in keys:
            name = key_label(header, c) or key_names.get(c, f"key{c}")
            if name in [v for k, v in key_names.items() if k != c]:
                name = paths[c] or f"{name} ({c})"  # two key columns with the same label: use the full path
            key_names[c] = name
        row_keys = {key_names[c]: current.get(c, "") for c in keys if current.get(c, "")}
        for c in range(ncols):
            if c in keys or not r[c]:
                continue
            value, notes, ok = parse_value(r[c])
            if not ok and first_line(r[c]) != r[c]:
                value, notes, ok = parse_value(first_line(r[c]))
            records.append({"row": row_no, "group": group, "keys": row_keys, "column": paths[c],
                            "value": value, "value_raw": r[c], "footnotes": ",".join(notes), "is_number": ok})
    return records


def side_by_side(cells: list[list[str]], shaded: list[bool]) -> list[list[int]]:
    """Column blocks for tables printed as two or more copies side by side (same header repeated)."""
    ncols = len(cells[0])
    head = [r for r, s in zip(cells, shaded) if s][:4]
    if not head:
        return [list(range(ncols))]
    labels = [" ".join(r[c] for r in head if r[c]) for c in range(ncols)]
    for p in range(2, ncols // 2 + 1):
        if ncols % p == 0 and labels[0] and all(labels[c] == labels[c + p] for c in range(ncols - p)):
            return [list(range(b, b + p)) for b in range(0, ncols, p)]
    return [list(range(ncols))]


def main(pdf_path: str, out_dir: str, sections: str = "BD") -> None:
    out = Path(out_dir)
    pdf = pdfplumber.open(pdf_path)
    rows, stats, no_values = [], Counter(), []
    for pn, page in enumerate(pdf.pages, 1):
        text = page.extract_text() or ""
        label = printed_label(text)
        if not label or label[0] not in sections or "intentionally left blank" in text.lower():
            continue
        tables = page.find_tables(TABLE_SETTINGS)
        if not tables:
            continue
        rects = gray_rects(page)
        heading = page_heading(page, min(t.bbox[1] for t in tables))
        lines = page_lines(pdf_path, pn)
        for ti, t in enumerate(tables, 1):
            raw = t.extract()
            shade = []
            for row in t.rows:
                cs = [c for c in row.cells if c]
                shade.append(bool(cs) and sum(shaded_fraction(c, rects) for c in cs) / len(cs) > 0.5)
            cells, flags = expand(raw, shade)
            keep = [c for c in range(len(cells[0])) if any(r[c] for r in cells)] if cells else []
            if not keep:
                continue
            cells = [[r[c] for c in keep] for r in cells]
            recs = []
            for block in side_by_side(cells, flags):
                part = convert([[r[c] for c in block] for r in cells], flags)
                base = max((r["row"] for r in recs), default=0)
                for rec in part:
                    rec["row"] += base
                recs += part
            if recs and not any(r["column"] for r in recs) and (not any(r["group"] for r in recs) or all(
                    is_number(v) for r in recs for k, v in r["keys"].items() if re.match(r"key\d+$", k))):
                stats["chart_grids_skipped"] += 1  # a figure's grid read as a table (e.g. B-27 685 force charts)
                continue
            for rec in recs:
                rec["column"] = rec["column"] or rec["group"]
            if not recs:
                stats["tables_without_values"] += 1
                no_values.append({"page": pn, "printed_label": label, "table": ti, "heading": heading,
                                  "first_row": " | ".join(x for x in cells[0] if x)[:200]})
                continue
            by_row: dict[int, list[str]] = {}
            for rec in recs:
                toks = NUM.findall(re.sub(r"\(\d+\)", "", rec["value_raw"]).replace(",", "").replace("‐", " ").replace("-", " "))
                by_row.setdefault(rec["row"], []).extend(toks)
            # Second reader: "line" = the row's numbers, in order, on one pdftotext line; "window" = in order
            # within up to four consecutive lines (layouts that centre a row's cells vertically).
            def in_order(seq, toks):
                it = iter(toks)
                return all(any(t == s for t in it) for s in seq)
            line_ok = {r for r, seq in by_row.items() if not seq or any(" " + " ".join(seq) + " " in ln for ln in lines)}
            def within(seq, toks):  # every number present, as a multiset (cells merged across lines move order)
                have = Counter(toks)
                return all(have[k] >= n for k, n in Counter(seq).items())
            win_ok = {r for r, seq in by_row.items() if r not in line_ok and any(
                in_order(seq, w) or within(seq, w)
                for w in (" ".join(lines[i:i + 4]).replace(",", "").split() for i in range(len(lines))))}
            for rec in recs:
                rows.append({"page": pn, "printed_label": label, "section": label[0], "table": ti,
                             "heading": heading, "group": rec["group"],
                             "keys": json.dumps(rec["keys"], ensure_ascii=False), "column": rec["column"],
                             "value": "" if rec["value"] is None else f"{rec['value']:.12g}",
                             "value_raw": rec["value_raw"], "footnotes": rec["footnotes"],
                             "is_number": int(rec["value"] is not None), "row": rec["row"],
                             "confirmed": "line" if rec["row"] in line_ok else "window" if rec["row"] in win_ok else ""})
            stats["tables"] += 1
    with open(out / "table_values.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for s in sections:
        sub = [r for r in rows if r["section"] == s]
        nums = [r for r in sub if r["is_number"] == 1]
        line = sum(r["confirmed"] == "line" for r in nums)
        win = sum(r["confirmed"] == "window" for r in nums)
        print(f"{s}: {len(nums)} numeric values: {line} confirmed on one line, {win} within 4 lines, "
              f"{len(nums) - line - win} unconfirmed; {len(sub) - len(nums)} text cells")
    with open(out / "table_values_text_only.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["page", "printed_label", "table", "heading", "first_row"])
        w.writeheader()
        w.writerows(no_values)
    print(dict(stats))


if __name__ == "__main__":
    main(*sys.argv[1:])
