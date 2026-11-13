"""Second, independent reading: confirm every extracted value row against poppler's pdftotext.

pdfplumber (pdfminer) does the extraction; this script re-reads each page with
`pdftotext -layout` (poppler, a different PDF engine) and checks that each row of
values (one coefficient across all openings) appears on one text line, in order.

Usage:
    python extract/crosscheck.py data/source/d103182x012.pdf data
Writes data/crosscheck.csv (one row per config/coefficient) and prints the match rate.
"""
from __future__ import annotations

import csv
import re
import subprocess
import sys
from collections import defaultdict

NUM = re.compile(r"^[<>]?(\d*\.\d+|\d{1,3}(?:,\d{3})+|\d+)(\(\d+\))?$")


def page_lines(pdf: str, page: int) -> list[list[str]]:
    txt = subprocess.run(["pdftotext", "-layout", "-f", str(page), "-l", str(page), pdf, "-"],
                         capture_output=True, text=True).stdout
    out = []
    for line in txt.splitlines():
        toks = [re.sub(r"\(\d+\)$", "", t) for t in line.split() if NUM.match(t)]
        if toks:
            out.append(toks)
    return out


def contains(seq: list[str], toks: list[str]) -> bool:
    n = len(seq)
    return any(toks[i:i + n] == seq for i in range(len(toks) - n + 1))


def main(pdf: str, data_dir: str) -> None:
    pages = {r["config_id"]: int(r["page"]) for r in csv.DictReader(open(f"{data_dir}/configs.csv"))}
    rows: dict[tuple[str, str], list[tuple[float, str]]] = defaultdict(list)
    for v in csv.DictReader(open(f"{data_dir}/coefficients.csv", encoding="utf-8")):
        if v["position"] != "" and v["value"] != "":
            raw = re.sub(r"\(\d+\)$", "", v["value_raw"].replace(" ", ""))
            rows[(v["config_id"], v["coefficient"])].append((float(v["position"]), raw))
    cache: dict[int, list[list[str]]] = {}
    results = []
    for (cid, coeff), pts in rows.items():
        if coeff == "HoleType":
            continue
        pg = pages[cid]
        if pg not in cache:
            cache[pg] = page_lines(pdf, pg)
        seq = [raw for _, raw in sorted(pts)]
        lines = cache[pg]
        if any(contains(seq, toks) for toks in lines):
            status = "match"
        elif any(contains(seq, a + b) for a, b in zip(lines, lines[1:])):
            status = "match_wrapped"  # pdftotext split the row over two lines
        else:
            status = "no_match"
        results.append((cid, coeff, pg, len(seq), status, " ".join(seq)))
    with open(f"{data_dir}/crosscheck.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["config_id", "coefficient", "page", "n_values", "status", "values"])
        w.writerows(results)
    counts = defaultdict(int)
    for r in results:
        counts[r[4]] += 1
    total = len(results)
    print(f"rows checked {total}: " + ", ".join(f"{k} {v} ({v / total:.1%})" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main(*sys.argv[1:])
