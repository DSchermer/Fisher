"""Convert the Catalog 14 pressure-drop-method tables (sections A and C) to one row per value.

Each value is a maximum allowable pressure drop for one actuator construction. Output columns:
  page, printed_label, section               where it is printed (pages.csv gives each page's heading:
                                              valve, actuator, class ...)
  group                                       row-group label, e.g. "2.5 Inch Port"
  keys                                        row keys as JSON, e.g. {"Travel, Inch": "1.5", "Actuator Size": "68"}
  column                                      the full column header path, e.g. "Size 70 › 33 psig › 10.1 psig"
  unit, value, value_raw                      psi or bar
  confirmed                                   1 if the row's values appear, in order, on one line of poppler's text

Usage:
    python extract/catalog14_dp.py data/source/d103428x012.pdf data/catalog14
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog14_tables import page_heading, printed_label  # noqa: E402
from parse_tables import TABLE_SETTINGS, clean, parse_value  # noqa: E402
from reference_tables import expand  # noqa: E402

KEY_WORDS = re.compile(r"travel|yoke|act\w*\s*size|valve\s*(body\s*)?size|\bnps\b|angle|shaft|port\s*dia|"
                       r"rotation|liner|disk\s*style|material|seal\b|trim\b", re.I)  # "Actator": sic
KEY_VALUE = re.compile(r"^[\d\s\-/.,_°xX()i]+$|^\d+(\.\d+)?\s*(and|&|or)\s*\d+")  # "45, 45i", "130(2)"
GROUP_ROW = re.compile(r"inch port|port\b|leakage|flow|class|rotation|push|shaft|seal|bearing|size", re.I)
NUM = re.compile(r"-?\d*\.\d+|\d+")


def norm(t: str) -> str:
    t = t.replace("_", "°") if re.fullmatch(r"\d+_", t) else t
    return re.sub(r"\s+", " ", t).strip()


def is_key_value(t: str) -> bool:
    return bool(t) and bool(KEY_VALUE.match(t)) and bool(re.search(r"\d", t))


def page_lines(pdf_path: str, page: int) -> list[str]:
    """Each pdftotext line reduced to its numbers, space-separated (dashes and words dropped)."""
    txt = subprocess.run(["pdftotext", "-layout", "-f", str(page), "-l", str(page), pdf_path, "-"],
                         capture_output=True, text=True).stdout
    return [" " + " ".join(NUM.findall(re.sub(r"\(\d+\)", "", line).replace(",", "").replace("‐", " ")
                                     .replace("-", " "))) + " "
            for line in txt.splitlines()]


def is_data_row(r: list[str], after_data: bool = False) -> bool:
    """A row of values: a key in the first cell (or, continuing a block of data rows, a first cell
    merged with the row above) and cells that are mostly numbers or dashes."""
    cells = [x for x in r[1:] if x]
    numeric = [x for x in cells if parse_value(x)[0] is not None or re.fullmatch(r"[-‐\s]+", x)]
    if not numeric or len(numeric) < len(cells) / 2:
        return False
    return is_key_value(r[0]) or (not r[0] and after_data)


def is_title_row(r: list[str]) -> bool:
    """A line spanning the whole table (text only in the first cell), e.g. "2.5 Inch Port"."""
    return bool(r[0]) and not any(r[1:]) and not is_key_value(r[0])


def build_layout(header: list[list[str]], first_data_row: list[str]) -> dict:
    ncols = len(first_data_row)
    # Key columns are every column before the first value column, i.e. the first column whose header
    # is not a row-key name ("Valve Size", "Angle of Opening", ...). A key column with no header of its
    # own is part of a merged key cell and takes the key name to its left.
    def header_texts(c):
        return [r[c] for r in header if r[c]]
    vstart = next((c for c in range(1, ncols) if header_texts(c)
                   and not all(KEY_WORDS.search(t) for t in header_texts(c))), 1)
    key_cols = list(range(vstart))
    rows = [list(r) for r in header]
    # A header row labelled in the key columns ("Air to Cylinder, Psig" | 50 | 60 ...) names its values.
    for r in rows:
        label = " ".join(x for x in r[:vstart] if x)
        if label and not KEY_WORDS.search(label) and any(r[vstart:]):
            for c in range(vstart, ncols):
                if r[c]:
                    r[c] = f"{label} {r[c]}"
            for c in range(vstart):
                r[c] = ""
    for r in rows:  # a group header spreads right over the empty cells it spans
        for c in range(vstart + 1, ncols):
            if not r[c] and r[c - 1]:
                r[c] = r[c - 1]
    parts_by_col = []
    for c in range(ncols):
        parts = []
        for r in rows:
            if r[c] and r[c] not in parts:
                parts.append(r[c])
        parts_by_col.append(parts)
    # Header text shared by every value column becomes the table's column heading; paths keep the rest.
    value_parts = [parts_by_col[c] for c in range(vstart, ncols)]
    common = [p for p in value_parts[0] if all(p in vp for vp in value_parts)] if value_parts else []
    paths = [" › ".join(p for p in parts if p not in common) or " › ".join(parts) for parts in parts_by_col]
    key_names = []
    for c in key_cols:
        names = [r[c] for r in header if r[c] and KEY_WORDS.search(r[c])]
        key_names.append(names[-1] if names else (key_names[-1] if key_names else f"key{c}"))
    return {"ncols": ncols, "key_cols": key_cols, "key_names": key_names, "paths": paths,
            "column_heading": " › ".join(common)}


def convert(cells: list[list[str]], template: dict | None):
    """Return (records, layout) for one table, or (None, None) if it is not a ΔP table.

    Rows are read top to bottom: title rows set the group; header rows are collected and become the
    column paths when the next data row arrives (a table can restart its header partway down);
    a table with no header continues the previous table's layout.
    """
    ncols = len(cells[0])
    # A label wrapped over three lines such as "Nitrile / or / PTFE" becomes one value.
    for i in range(len(cells) - 2):
        for c in range(min(4, ncols)):
            if cells[i + 1][c] in ("or", "and") and cells[i][c] and cells[i + 2][c]:
                cells[i][c] = f"{cells[i][c]} {cells[i + 1][c]} {cells[i + 2][c]}"
                cells[i + 1][c] = cells[i + 2][c] = ""
    layout = template if template and template["ncols"] == ncols else None
    records, group, header, current = [], "", [], {}
    row_no = 0
    prev_data = False
    for r in cells:
        if not any(r):
            continue
        if is_title_row(r):
            prev_data = False
            text = r[0]
            if not (re.match(r"^\d+\.\s", text) or text.lower().startswith("note")):
                group = text
            continue
        if not is_data_row(r, prev_data):
            header.append(r)
            prev_data = False
            continue
        prev_data = True
        row_no += 1
        if header and any(any(x for x in h[1:]) for h in header):
            layout = build_layout(header, r)
            current = {}
        header = []
        if layout is None:
            return None, None
        # One logical key per name: the cell printed in this row, else the value carried down.
        for name in dict.fromkeys(layout["key_names"]):
            cols = [c for c, n in zip(layout["key_cols"], layout["key_names"]) if n == name]
            here = next((r[c] for c in cols if r[c]), "")
            if here:
                current[name] = norm(here)
        keys = {name: current.get(name, "") for name in dict.fromkeys(layout["key_names"])}
        for c in range(max(layout["key_cols"]) + 1, ncols):
            raw = r[c]
            if not raw:
                continue
            v, notes, ok = parse_value(raw)
            path = layout["paths"][c]
            unit = "bar" if re.search(r"\bbar$", path, re.I) else "psi"
            records.append({"row": row_no, "group": group, "keys": keys, "column": path, "unit": unit,
                            "column_heading": layout.get("column_heading", ""),
                            "value": v, "value_raw": raw, "footnotes": ",".join(notes), "parse_ok": ok})
    return (records, layout) if records else (None, None)


def main(pdf_path: str, out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pdf = pdfplumber.open(pdf_path)
    rows, template, last_heading, skipped = [], None, "", []
    for pn, page in enumerate(pdf.pages, 1):
        text = page.extract_text() or ""
        label = printed_label(text)
        if not label or label[0] not in "AC" or "intentionally left blank" in text.lower():
            continue
        tables = page.find_tables(TABLE_SETTINGS)
        if not tables:
            continue
        heading = page_heading(page, min(t.bbox[1] for t in tables))
        if "Maximum Allowable" not in text and "ΔP" not in text and "P)" not in text:
            continue
        if not heading.strip(" |"):
            heading = last_heading  # continued from the previous page
        last_heading = heading
        lines = page_lines(pdf_path, pn)
        for ti, t in enumerate(tables):
            cells = expand(t.extract())
            cells = [r[:-1] for r in cells]  # drop expand()'s stacked marker
            keep = [c for c in range(len(cells[0])) if any(r[c] for r in cells)]
            cells = [[r[c] for c in keep] for r in cells]
            recs, layout = convert(cells, template)
            if not recs:
                skipped.append(label)
                continue
            template = layout
            # Second reader: a row's values, in order, must appear on one pdftotext line.
            by_row: dict[int, list[str]] = {}
            for rec in recs:
                if rec["value"] is not None:
                    by_row.setdefault(rec["row"], []).append(f"{rec['value']:g}" if "." not in rec["value_raw"]
                                                             else re.sub(r"\(.*", "", rec["value_raw"]).strip())
            ok_rows = {r for r, seq in by_row.items() if any(" " + " ".join(seq) + " " in ln for ln in lines)}
            for rec in recs:
                rows.append({"page": pn, "printed_label": label, "section": label[0], "heading": heading,
                             "group": rec["group"], "keys": json.dumps(rec["keys"], ensure_ascii=False),
                             "column_heading": rec["column_heading"],
                             "column": rec["column"], "unit": rec["unit"],
                             "value": "" if rec["value"] is None else f"{rec['value']:g}",
                             "value_raw": rec["value_raw"], "footnotes": rec["footnotes"],
                             "parse_ok": int(rec["parse_ok"]),
                             "confirmed": int(rec["row"] in ok_rows)})
    # Page headings go to pages.csv once per page instead of on every value row.
    pages = {}
    for r in rows:
        pages.setdefault(r["page"], {"page": r["page"], "printed_label": r["printed_label"],
                                     "section": r["section"], "heading": r.pop("heading")})
        r.pop("heading", None)
    with open(out / "pages.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["page", "printed_label", "section", "heading"])
        w.writeheader()
        w.writerows(pages.values())
    fields = ["page", "printed_label", "section", "group", "keys", "column_heading", "column", "unit", "value",
              "value_raw", "footnotes", "parse_ok", "confirmed"]
    with open(out / "allowable_dp.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    vals = [r for r in rows if r["value"] != ""]
    print(f"values {len(vals)} (A {sum(r['section'] == 'A' for r in vals)}, C {sum(r['section'] == 'C' for r in vals)}), "
          f"confirmed {sum(r['confirmed'] for r in vals)}, unparsed {sum(1 for r in rows if not r['parse_ok'])}")
    print("tables skipped (not a ΔP layout):", " ".join(sorted(set(skipped))))


if __name__ == "__main__":
    main(*sys.argv[1:])
