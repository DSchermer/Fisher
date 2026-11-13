"""Extract every ruled table in Fisher Catalog 14 (Actuator Sizing, D103428X012) as printed.

Writes data/catalog14/tables/<id>.csv and data/catalog14/index.csv. Each index row records the
page, printed label, section (A-D), the page heading (actuator, valve, class ...), the table title,
size, and how many rows a second PDF reader (poppler) confirms.

Usage:
    python extract/catalog14_tables.py data/source/d103428x012.pdf data/catalog14
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_tables import TABLE_SETTINGS, clean  # noqa: E402
from reference_tables import confirmed_rows, extract_table, slug, title_above  # noqa: E402

SECTIONS = {
    "A": "Actuator sizing for sliding-stem valves, pressure drop method",
    "B": "Actuator sizing for sliding-stem valves, force method",
    "C": "Actuator sizing for rotary valves, pressure drop method",
    "D": "Actuator sizing for rotary valves, torque method",
}
SKIP_LINE = re.compile(r"^(Catalog 14|Page [A-D][‐-]?[\d.]+|\w+ \d{4}|.*\d{4} - Page|Actuator Sizing for)", re.I)


def printed_label(text: str) -> str:
    m = re.search(r"Page ([A-D])[‐-](\d+(?:\.\d+)?)", text)
    return f"{m.group(1)}-{m.group(2)}" if m else ""


def page_heading(page, top: float) -> str:
    """Text lines above the first table, without the running header (catalog, page, date)."""
    words = [w for w in page.extract_words(keep_blank_chars=True, x_tolerance=2) if w["bottom"] <= top]
    lines: dict[int, list] = {}
    for w in words:
        lines.setdefault(round(w["top"] / 3), []).append(w)
    out = []
    for k in sorted(lines):
        for w in sorted(lines[k], key=lambda w: w["x0"]):
            t = clean(w["text"])
            if t and not SKIP_LINE.match(t) and t not in out:
                out.append(t)
    return " | ".join(out)


def main(pdf_path: str, out_dir: str) -> None:
    out = Path(out_dir)
    (out / "tables").mkdir(parents=True, exist_ok=True)
    pdf = pdfplumber.open(pdf_path)
    index = []
    for pn, page in enumerate(pdf.pages, 1):
        text = page.extract_text() or ""
        label = printed_label(text)
        if not label or "intentionally left blank" in text.lower():
            continue
        tables = page.find_tables(TABLE_SETTINGS)
        if not tables:
            continue
        heading = page_heading(page, min(t.bbox[1] for t in tables))
        for ti, t in enumerate(tables):
            try:
                headers, rows = extract_table(t)
            except (IndexError, ValueError):
                continue
            if not rows or not any(re.search(r"\d", " ".join(r)) for r in rows):
                continue
            title = title_above(page, t)
            tid = f"{label.replace('-', '_').replace('.', '_')}_t{ti + 1}"
            if title:
                tid += "_" + slug(title)[:40]
            with open(out / "tables" / f"{tid}.csv", "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(headers)
                w.writerows(rows)
            index.append({"id": tid, "page": pn, "printed_label": label, "section": label[0],
                          "heading": heading, "title": title, "rows": len(rows), "columns": len(headers),
                          "rows_confirmed": confirmed_rows(pdf_path, pn, rows)})
    with open(out / "index.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["id", "page", "printed_label", "section", "heading", "title",
                                           "rows", "columns", "rows_confirmed"])
        w.writeheader()
        w.writerows(index)
    rows_total = sum(i["rows"] for i in index)
    conf = sum(i["rows_confirmed"] for i in index)
    print(f"tables {len(index)}, rows {rows_total}, confirmed by second reader {conf} ({conf / rows_total:.1%})")
    for s in "ABCD":
        sub = [i for i in index if i["section"] == s]
        print(f"  {s}: {len(sub)} tables, {sum(i['rows'] for i in sub)} rows, "
              f"{sum(i['rows_confirmed'] for i in sub)} confirmed  ({SECTIONS[s]})")


if __name__ == "__main__":
    main(*sys.argv[1:])
