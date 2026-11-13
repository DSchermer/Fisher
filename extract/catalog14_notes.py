"""Catalog 14 table footnotes: the numbered notes printed directly under each table, so that the
footnote numbers kept on values ("1424(1)") can be looked up. Procedure text (numbered steps) is not
collected: only the band below a table, up to the next table or 160 points, whichever is nearer.

Writes data/catalog14/page_notes.csv (page, printed_label, table, number, text).

Usage:
    python extract/catalog14_notes.py data/source/d103428x012.pdf data/catalog14
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog14_tables import printed_label  # noqa: E402
from parse_tables import TABLE_SETTINGS, clean  # noqa: E402

NOTE = re.compile(r"^(\d{1,2})\.\s+(\S.*)$")


def main(pdf_path: str, out_dir: str) -> None:
    pdf = pdfplumber.open(pdf_path)
    out = []
    for pn, page in enumerate(pdf.pages, 1):
        text = page.extract_text() or ""
        label = printed_label(text)
        if not label:
            continue
        tables = sorted(page.find_tables(TABLE_SETTINGS), key=lambda t: t.bbox[1])
        for ti, t in enumerate(tables, 1):
            # footnotes inside the table's own last rows (a ruled footnote row) or just below it
            nxt = next((u.bbox[1] for u in tables if u.bbox[1] > t.bbox[3] + 1), page.height)
            bottom = min(nxt, t.bbox[3] + 160, page.height - 40)
            top = max(t.bbox[1], t.bbox[3] - 60)
            band = page.crop((max(0, t.bbox[0] - 10), top, min(page.width, t.bbox[2] + 10), bottom))
            current = None
            for line in (band.extract_text() or "").splitlines():
                line = clean(line)
                m = NOTE.match(line)
                if m and not re.match(r"^[\d.\s-]+$", m.group(2)):
                    current = {"page": pn, "printed_label": label, "table": ti, "number": int(m.group(1)),
                               "text": m.group(2)}
                    out.append(current)
                elif current and line and not re.match(r"^(Table|Figure|Catalog|Page|E \d{4})", line) \
                        and current["text"][-1] not in ".)" and len(line) < 200:
                    current["text"] += " " + line  # a footnote wrapped onto the next line
                else:
                    current = None
    seen, rows = set(), []
    for r in out:
        k = (r["page"], r["table"], r["number"])
        if k not in seen:
            seen.add(k)
            rows.append(r)
    with open(Path(out_dir) / "page_notes.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["page", "printed_label", "table", "number", "text"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} footnotes on {len({r['page'] for r in rows})} pages")


if __name__ == "__main__":
    main(*sys.argv[1:])
