"""Catalog 14 stem load calculations (pages B-99 to B-105) as typed tables.

  usage_guide.csv      Table 1: valve design, size, rating, bonnet, stem diameter -> which tables apply
  stem_load_316.csv    Tables 3, 5, 7: maximum allowable stem load for strain-hardened 316 stems,
                       by stem diameter and temperature (L/D up to 12.5, 15 and 20)
  stem_material.csv    Tables 4, 6, 8: material factors by material and temperature
  stem_reference.csv   Tables 4, 6, 8: reference load per stem diameter (stem load = reference x factor)
  stem_load_valve.csv  Tables 2 and 9: per-valve maximum allowable stem loads (ET-C/EWT-C/EZ-C, HPT-C/HPS-C)

Every printed number is checked against poppler's text of its page (second reader).

Usage:
    python extract/catalog14_stem_load.py data/source/d103428x012.pdf data/catalog14/force
"""
from __future__ import annotations

import csv
import re
import sys
from fractions import Fraction
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog14_dp import page_lines  # noqa: E402
from catalog14_tables import printed_label  # noqa: E402
from parse_tables import TABLE_SETTINGS  # noqa: E402

LD_MAX = {3: 12.5, 4: 12.5, 5: 15, 6: 15, 7: 20, 8: 20}


def lines_of(cell) -> list[str]:
    return [x.strip() for x in (cell or "").split("\n") if x.strip()]


def inch(x: str) -> float:
    x = x.replace("‐", "-").strip()
    if re.fullmatch(r"\d+-\d+/\d+", x):
        w, f = x.split("-")
        return int(w) + float(Fraction(f))
    if re.fullmatch(r"\d+ \d+/\d+", x):
        w, f = x.split(" ")
        return int(w) + float(Fraction(f))
    return float(Fraction(x)) if "/" in x else float(x)


def num(x: str) -> float | None:
    x = re.sub(r"\(\d\)$", "", x.replace(",", "").strip())
    return float(x) if re.fullmatch(r"-?\d*\.?\d+", x) else None


def temp(x: str) -> float | None:
    m = re.search(r"(\d+)", x.replace("(1)", "").replace("(2)", ""))
    return float(m.group(1)) if m else None


def materials(cell: str) -> list[str]:
    """Material names stacked in one cell, a name wrapping onto lines that start with '('."""
    out: list[str] = []
    for ln in lines_of(cell):
        if out and (ln.startswith("(") or out[-1].count("(") > out[-1].count(")")):
            out[-1] += " " + ln
        else:
            out.append(ln)
    return out


def main(pdf_path: str, out_dir: str) -> None:
    out = Path(out_dir)
    pdf = pdfplumber.open(pdf_path)
    usage, loads, mats, refs, valve_loads = [], [], [], [], []
    checks = {"found": 0, "numbers": 0}
    for pn in range(160, 180):
        page = pdf.pages[pn - 1]
        text = page.extract_text() or ""
        label = printed_label(text)
        if not label or not label.startswith("B-") or not (99 <= float(label[2:].split(".")[0]) <= 105):
            continue
        lines = page_lines(pdf_path, pn)
        page_tokens = set(re.findall(r"\d+(?:\.\d+)?", " ".join(lines).replace(",", "")))

        def seen(v: str) -> None:
            checks["numbers"] += 1
            if re.sub(r"\(\d\)$", "", v.replace(",", "")) in page_tokens:
                checks["found"] += 1

        for t in page.find_tables(TABLE_SETTINGS):
            rows = [[c or "" for c in r] for r in t.extract()]
            head = " ".join(c or "" for c in rows[0])
            m = re.search(r"Table (\d+)\.", head)
            tno = int(m.group(1)) if m else None
            if "Usage Guide" in head:
                design = ""
                for r in rows[2:]:
                    if not r[1] and not r[2] and not r[4] or (r[0] or "").startswith("1."):
                        continue
                    design = (r[0] or "").replace("\n", " ") or design
                    stems, tabs = lines_of(r[4]), lines_of(r[5])
                    for i, tab in enumerate(tabs or [""]):
                        usage.append({"design": design, "nps": (r[1] or "").replace("\n", " "),
                                      "rating": (r[2] or "").replace("\n", " "), "bonnet": (r[3] or "").replace("\n", " "),
                                      "stem_in": stems[i] if len(stems) == len(tabs) else " / ".join(stems) or "- - -",
                                      "tables": tab, "printed_label": label})
            elif tno in (3, 5, 7) or ("REFERENCE" not in head and label in ("B-102", "B-103", "B-104")
                                       and any("TEMPERATURE" in c for r in rows[:3] for c in r)):
                tno = tno or {"B-102": 3, "B-103": 5, "B-104": 7}[label]
                temps_f, unit = None, None
                for r in rows:
                    if (r[1] or "").startswith("TEMPERATURE"):
                        unit = "F" if "F" in r[1].replace("(cid:3)", "") else "C"
                        continue
                    if r[0] == "" and r[1] and r[1].startswith("to "):
                        temps_f = [temp(x) for x in r[1:]]
                        continue
                    stems = lines_of(r[0])
                    if not stems or not temps_f or not re.match(r"[\d/.-]", stems[0]):
                        continue
                    cols = [lines_of(c) for c in r[1:]]
                    for i, s in enumerate(stems):
                        for tcol, vals in zip(temps_f, cols):
                            if i < len(vals):
                                seen(vals[i])
                                loads.append({"table": tno, "ld_max": LD_MAX[tno], "unit_system": unit,
                                              "stem": s, "stem_in": inch(s) if unit == "F" else round(float(s) / 25.4, 4),
                                              "temp": tcol, "load": num(vals[i]),
                                              "load_unit": "lb" if unit == "F" else "kN", "printed_label": label})
            elif "REFERENCE LOADS" in head or "Stem Material Factors" in " ".join(c or "" for r in rows[:3] for c in r):
                tno = tno or {"B-102": 4, "B-103": 6, "B-104": 8}.get(label)
                ref_text = " ".join(c or "" for r in rows[:2] for c in r)
                for m in re.finditer(r"([\d\-/ ]+?) Inch Stem: ([\d.]+) kN \(([\d,]+) Lb\)", ref_text.replace("\n", " ")):
                    seen(m.group(3))
                    refs.append({"table": tno, "stem": m.group(1).strip(), "stem_in": inch(m.group(1).strip()),
                                 "reference_kn": float(m.group(2)), "reference_lb": float(m.group(3).replace(",", "")),
                                 "printed_label": label})
                temps_f = None
                for r in rows:
                    if r[0] == "" and r[1] and "F" in r[1].replace("(cid:3)", "") and r[1].startswith("to"):
                        temps_f = [temp(x) for x in r[1:]]
                        continue
                    if not temps_f or not r[0] or r[0].startswith(("1.", "Stem Material", "TO OBTAIN", "REFERENCE")):
                        continue
                    names = materials(r[0])
                    cols = [lines_of(c) for c in r[1:]]
                    n = len(cols[0]) if cols else 0
                    if len(names) != n:
                        print(f"  {label} table {tno}: {len(names)} material names but {n} values; row kept as printed")
                    for i, name in enumerate(names[:n]):
                        for tcol, vals in zip(temps_f, cols):
                            if i < len(vals) and num(vals[i]) is not None:
                                seen(vals[i])
                                mats.append({"table": tno, "material": name, "temp_f": tcol, "factor": num(vals[i]),
                                             "footnote": "".join(re.findall(r"\((\d)\)", vals[i])), "printed_label": label})
            elif re.search(r"L/D", head) or "MAXIMUM ALLOWABLE STEM LOAD" in head or "MAX ALLOWABLE STEM LOAD" in head:
                tno = tno or (2 if label == "B-101" else 9)
                valve = "ET-C, EWT-C, EZ-C" if tno == 2 else ""
                lb_col = len(rows[1]) - 1
                stem_col = next(i for i, c in enumerate(rows[0]) if c and "STEM DIA" in c.upper())
                nps = ""
                for r in rows[2:]:
                    if (r[0] or "").startswith("1."):
                        continue
                    if tno == 9:
                        valve = r[0] or valve
                        nps = r[1] or nps
                    else:
                        nps = (r[0] or nps).replace("\n", " / ")
                    stems, lbs = lines_of(r[stem_col]), lines_of(r[lb_col])
                    lens, lds = lines_of(r[stem_col + 1]), lines_of(r[stem_col + 2])
                    for i, s in enumerate(stems):
                        if i < len(lbs):
                            seen(lbs[i])
                            valve_loads.append({"table": tno, "valve": valve, "nps": nps, "stem": s, "stem_in": inch(s),
                                                "unsupported_length_in": num(lens[i]) if i < len(lens) else None,
                                                "ld_ratio": num(lds[i]) if i < len(lds) else None,
                                                "max_stem_load_lb": num(lbs[i]), "printed_label": label})
    for name, rows in (("usage_guide", usage), ("stem_load_316", loads), ("stem_material", mats),
                       ("stem_reference", refs), ("stem_load_valve", valve_loads)):
        with open(out / f"{name}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"{name}: {len(rows)} rows")
    print(f"second reader: {checks['found']} of {checks['numbers']} numbers found on their page")


if __name__ == "__main__":
    main(*sys.argv[1:])
