"""Typed values for every Catalog 14 table in the force method (section B) and torque method (section D).

The same treatment sections A and C get in catalog14_dp.py, generalized for the more varied B and D
layouts:
  - header rows are the gray-shaded rows (Catalog 14 shades every header row and row-group label);
    a shaded block after data starts a new header for the rows below it;
  - a row whose only text spans the table is a row-group label, e.g. "1.5 Inch Port";
  - key columns: the first column, columns whose header names a key (size, shaft, bearing, ...),
    and columns holding text (part numbers, materials); merged key cells are carried down;
  - every other cell is a value, with its full column header path;
  - a value printed once in a cell merged over several rows is repeated on each row it covers
    (merged = 1), and checked by the second reader on the row where it is printed;
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


class Spanned(str):
    """An empty cell covered by a merged cell to its left (a group header spanning columns)."""


def horizontal_spans(table) -> list[list[bool]]:
    """For each cell: is it covered by a merged cell to its left in the same row?"""
    ncols = max(len(r.cells) for r in table.rows)
    col_x0 = [min((r.cells[c][0] for r in table.rows if c < len(r.cells) and r.cells[c]), default=1e9)
              for c in range(ncols)]
    out = []
    for r in table.rows:
        row, left = [], None
        for c in range(ncols):
            cell = r.cells[c] if c < len(r.cells) else None
            row.append(cell is None and left is not None and left[2] > col_x0[c] + 1)
            if cell is not None:
                left = cell
        out.append(row)
    return out


class Covered(str):
    """An empty cell covered by a merged cell above it: the value printed above applies here too."""


def vertical_spans(table) -> list[list[bool]]:
    """For each cell: is it covered by a merged cell above it in the same column?"""
    ncols = max(len(r.cells) for r in table.rows)
    out, above = [], [None] * ncols
    for r in table.rows:
        top = r.bbox[1]
        row = []
        for c in range(ncols):
            cell = r.cells[c] if c < len(r.cells) else None
            row.append(cell is None and above[c] is not None and above[c][3] > top + 1)
            if cell is not None:
                above[c] = cell
        out.append(row)
    return out


def expand(raw, shade, spans=None, vspans=None):
    """split_rows with the shaded flag kept for each expanded row; spanned cells marked."""
    rows, flags = [], []
    for i, (r, s) in enumerate(zip(raw, shade)):
        sub = split_rows([r])
        if vspans:
            for j in range(len(sub)):
                sub[j] = [Covered("") if vspans[i][c] and not x else x for c, x in enumerate(sub[j])]
        for j in range(1, len(sub)):  # a single value beside a stack of lines covers the whole stack
            sub[j] = [Covered("") if not x and sub[0][c] and not isinstance(sub[0][c], Covered) else x
                      for c, x in enumerate(sub[j])]
        if spans:
            sub[0] = [Spanned("") if spans[i][c] and not x else x for c, x in enumerate(sub[0])]
        rows += sub
        flags += [s] * len(sub)
    return rows, flags


def key_columns(header: list[list[str]], body: list[list[str]], ncols: int) -> list[int]:
    keys = [0]
    leading = True
    spread = column_paths(header, ncols, [])  # with group headers spread over every column they span
    for c in range(1, ncols):
        under_value = bool(re.match(r"^[ABCK](\(\d\))?( ›|$)", spread[c])) or bool(VALUE_HEADER.search(spread[c]))
        if under_value and leading:
            leading = False  # e.g. "A › ETFE Seal": a factor column, though "seal" names a key elsewhere
        own = [r[c] for r in header if r[c] and not UNIT_ONLY.match(r[c])]
        head = own[-1] if own else ""  # the column's own label, not the group headers above it
        cells = [r[c] for r in body if r[c]]
        text_cells = [x for x in cells if not is_valueish(x)]
        named_key = bool(KEY_HEADER.search(head)) and not VALUE_HEADER.search(" ".join(r[c] for r in header))
        if cells and len(text_cells) > len(cells) / 2:
            if not leading and (len(set(text_cells)) == 1 or re.match(r"^[ABCK](\(\d\))? ›", spread[c])):
                continue  # marks inside a factor's columns (θ / K in the C 75° column, D-12.1, D-18): values
            keys.append(c)  # a text column: materials, part numbers, descriptions
            continue
        if under_value:
            continue
        if leading and c == keys[-1] + 1 and (named_key or (KEY_HEADER.search(head)
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
    # Group headers spread right over the empty cells they span (value region only), but not past a
    # column where a header above starts a new group.
    for k, r in enumerate(rows):
        for c in range(1, ncols):
            spanned = isinstance(header[k][c], Spanned) or (
                not any(isinstance(h[c], Spanned) for h in header) and not any(header[j][c] for j in range(k)))
            if not r[c] and r[c - 1] and c not in keys and (c - 1) not in keys and spanned:
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
    records, header, group, current, row_no, last = [], header_first, "", {}, 0, {}
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
            last = {}
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
            if c in keys:
                continue
            text, merged = r[c], False
            if not text and isinstance(text, Covered) and last.get(c):
                text, merged = last[c], True  # printed once in a cell merged over several rows
            if not text:
                continue
            last[c] = text
            value, notes, ok = parse_value(text)
            if not ok and first_line(text) != text:
                value, notes, ok = parse_value(first_line(text))
            records.append({"row": row_no, "group": group, "keys": row_keys, "column": paths[c],
                            "value": value, "value_raw": text, "footnotes": ",".join(notes), "is_number": ok,
                            "merged": merged})
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


def norm_tokens(text: str) -> list[str]:
    """Numbers in text, tokenised the same way for table cells and for the second reader's lines."""
    return NUM.findall(text.replace(",", "").replace("‐", " ").replace("-", " "))


def caption(page, table) -> str:
    """The line of text just above a table (its title, e.g. 'CL150 K Values for Effective Pressure Drop')."""
    top = table.bbox[1]
    if top < 5:
        return ""
    band = page.crop((0, max(0, top - 48), page.width, top))
    lines = [x.strip() for x in (band.extract_text() or "").splitlines() if x.strip()]
    titled = [x for x in lines if re.match(r"table \d", x, re.I)]
    return titled[-1] if titled else (lines[-1] if lines else "")


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
            cells, flags = expand(raw, shade, horizontal_spans(t), vertical_spans(t))
            keep = [c for c in range(len(cells[0])) if any(r[c] for r in cells)] if cells else []
            if not keep:
                continue
            cells = [[r[c] for c in keep] for r in cells]
            recs = []
            cap = caption(page, t)
            if not re.match(r"table \d", cap, re.I):  # a title printed inside the table's ruled box
                cap = next((x for r in cells for x in r if re.match(r"table \d+\.", x or "", re.I)), cap)
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
            # A merged cell's value is printed centred over all the rows it covers, possibly far from the
            # first of them: check it on its own, anywhere on the page, and the rest of its row as usual.
            merged_cols = {(rec["column"], rec["value_raw"]) for rec in recs if rec["merged"]}
            page_toks = Counter(norm_tokens(" ".join(lines)))
            by_row: dict[int, list[str]] = {}
            source_ok: dict[int, bool] = {}
            for rec in recs:
                if rec["merged"]:
                    continue  # printed in the row above; checked there
                toks = norm_tokens(re.sub(r"\(\d+\)", "", rec["value_raw"]))
                if (rec["column"], rec["value_raw"]) in merged_cols:
                    ok = all(page_toks[k] >= n for k, n in Counter(toks).items())
                    source_ok[rec["row"]] = source_ok.get(rec["row"], True) and ok
                    by_row.setdefault(rec["row"], [])
                    continue
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
                for w in (norm_tokens(" ".join(lines[i:i + 4])) for i in range(len(lines))))}
            line_ok -= {r for r, ok in source_ok.items() if not ok}
            win_ok -= {r for r, ok in source_ok.items() if not ok}
            # rows whose only numbers are merged-cell values: found on the page, nothing finer
            page_ok = {r for r, seq in by_row.items() if not seq and source_ok.get(r)}
            line_ok -= page_ok
            def label_of(row):
                return ("line" if row in line_ok else "window" if row in win_ok
                        else "page" if row in page_ok else "")
            source_label = {}  # a repeated merged value carries the result of the row where it is printed
            for rec in recs:
                key = (rec["column"], rec["value_raw"])
                if not rec["merged"]:
                    source_label[key] = label_of(rec["row"])
                rec["confirmed"] = source_label.get(key, "") if rec["merged"] else label_of(rec["row"])
            for rec in recs:
                rows.append({"page": pn, "printed_label": label, "section": label[0], "table": ti,
                             "heading": heading, "caption": cap, "group": rec["group"],
                             "keys": json.dumps(rec["keys"], ensure_ascii=False), "column": rec["column"],
                             "value": "" if rec["value"] is None else f"{rec['value']:.12g}",
                             "value_raw": rec["value_raw"], "footnotes": rec["footnotes"],
                             "is_number": int(rec["value"] is not None), "row": rec["row"],
                             "merged": int(rec["merged"]),
                             "confirmed": rec["confirmed"]})
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
        pg = sum(r["confirmed"] == "page" for r in nums)
        print(f"{s}: {len(nums)} numeric values: {line} confirmed on one line, {win} within 4 lines, "
              f"{pg} only found on the page, {len(nums) - line - win - pg} unconfirmed; "
              f"{len(sub) - len(nums)} text cells")
    with open(out / "table_values_text_only.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["page", "printed_label", "table", "heading", "first_row"])
        w.writeheader()
        w.writerows(no_values)
    print(dict(stats))


if __name__ == "__main__":
    main(*sys.argv[1:])
