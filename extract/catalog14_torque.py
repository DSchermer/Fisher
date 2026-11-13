"""Typed tables for the Catalog 14 torque method (rotary valves, section D).

So far: the 7600 butterfly valve (pages D-5/D-6), Table 1 torque characteristics. Writes data/catalog14/torque/. Every number is checked against poppler.

Usage:
    python extract/catalog14_torque.py data/source/d103428x012.pdf data/catalog14/torque
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog14_force import Extractor, carry, num, split_rows  # noqa: E402
from parse_tables import TABLE_SETTINGS, clean  # noqa: E402


def main(pdf_path: str, out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ex = Extractor(pdf_path)
    pdf = pdfplumber.open(pdf_path)
    rows = []
    for page, label in ((369, "D-5"), (370, "D-6")):
        raw = pdf.pages[page - 1].find_tables(TABLE_SETTINGS)[0].extract()
        for r in raw:
            cells = [(c or "") for c in r]
            if not re.match(r"[\d.]", clean(cells[3].split("\n")[0])):
                continue
            bearings = [clean(x) for x in re.split(r"\n(?=PTFE|Graphite|R30006)", cells[2]) if clean(x)]
            a_vals = [clean(x) for x in cells[3].split("\n") if clean(x)]
            shaft = clean(cells[1].split("\n")[0]).replace("‐", "-")
            shaft_class = clean(" ".join(cells[1].split("\n")[1:])).strip("()").replace("‐", "-")
            for bearing, a in zip(bearings, a_vals):
                rows.append({"valve": "7600", "nps": clean(cells[0]), "shaft_in": shaft, "shaft_class": shaft_class,
                             "bearing": bearing.replace("‐", "-"), "A": num(a), "B": num(clean(cells[4])),
                             "C_60": num(clean(cells[5])), "C_90": num(clean(cells[6])),
                             "max_torque_lbf_in": num(clean(cells[7])), "printed_label": label})
            ex.check("7600 table 1", page, [cells[0], cells[1], cells[3], cells[4], cells[5], cells[6], cells[7]])
    rows_list = rows
    last = ""  # valve size is printed once per group of shafts
    for r in rows_list:
        last = r["nps"] = r["nps"] or last
    with open(out / "torque_characteristics.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows_list[0]))
        w.writeheader()
        w.writerows(rows_list)
    total = sum(n for _, n, _ in ex.checks)
    bad = sum(m for _, _, m in ex.checks)
    print(f"7600 torque rows {len(rows_list)}; "
          f"second reader: {total - bad} of {total} numbers found on their page")


if __name__ == "__main__":
    main(*sys.argv[1:])
