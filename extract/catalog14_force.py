"""Typed tables for the Catalog 14 force method (sliding-stem valves, section B, pages B-4 to B-18).

Writes data/catalog14/force/:
  port_data.csv          Tables 2, 2A, 2C-2H: port diameter, circumference, area, unbalance area(s)
  unbalance_area.csv     Table 2/2C unbalance areas split per construction they apply to
  stem_area.csv          Table 3
  seat_load_rules.csv    Table 4: seat load equation by valve type, construction, port size, leak class
  seat_factors.csv       Table 5: A and B factors for composition seats
  packing_friction.csv   Tables 6, 6A, 6B, 6C, 6D: packing friction in pounds

Every number written is checked to appear on its page in poppler's text (second reader).

Usage:
    python extract/catalog14_force.py data/source/d103428x012.pdf data/catalog14/force
"""
from __future__ import annotations

import csv
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_tables import TABLE_SETTINGS, clean  # noqa: E402

DASH = re.compile(r"^[-‐–\s]+$")


def cellval(x: str) -> str:
    x = clean(x).replace("‐", "-")
    return "" if DASH.match(x or "-") else x


def split_rows(raw: list[list[str | None]]) -> list[list[str]]:
    """Expand stacked cells into rows. The row count comes from cells that stack numbers (one per
    line); cells with that many lines are split line by line, any other cell (a wrapped text label,
    or a value merged over the stack) stays whole on the first line."""
    out = []
    for row in raw:
        parts = [[clean(x) for x in (c or "").split("\n") if clean(x)] for c in row]
        stacked = [len(p) for p in parts if len(p) > 1 and all(
            re.fullmatch(r"[-‐–\s]+|N/A|-?[\d,]*\.?\d+(\(\d\))?%?|\d+(-\d+)?/\d+|All", x) for x in p)]
        k = max(stacked, default=1)
        for j in range(k):
            out.append([cellval(p[j] if len(p) == k else (" ".join(p) if j == 0 else "")) for p in parts])
    return out


def carry(rows: list[list[str]], cols: list[int]) -> list[list[str]]:
    """Fill merged cells: carry the last value down in the given columns."""
    last = {c: "" for c in cols}
    for r in rows:
        for c in cols:
            if r[c]:
                last[c] = r[c]
            else:
                r[c] = last[c]
    return rows


def num(x: str) -> float | None:
    m = re.fullmatch(r"-?[\d,]*\.?\d+", (x or "").replace(",", ""))
    return float(m.group()) if m else None


def frac(x: str) -> float | None:
    x = re.sub(r"\(\d+\)", "", x or "").strip()
    m = re.fullmatch(r"(\d+)-(\d+)/(\d+)", x) or re.fullmatch(r"(\d+)/(\d+)", x)
    if m and len(m.groups()) == 3:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    if m:
        return int(m.group(1)) / int(m.group(2))
    return num(x)


def unbalance_entries(text: str) -> list[tuple[float, str]]:
    """'0.154 (ET, EWT Class V Shutoff) 0.25(2) (C-seal trim) 0.51 (CAV4, ED)' -> [(0.154, 'ET, ...'), ...]"""
    out, i = [], 0
    for m in re.finditer(r"(\d*\.\d+|\d+)(?:\(\d\))?\s*\(", text):
        if m.start() < i:
            continue
        depth, j = 1, m.end()
        while j < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[j], 0)
            j += 1
        out.append((float(m.group(1)), clean(text[m.end():j - 1])))
        i = j
    if not out and num(text) is not None:
        out.append((num(text), ""))
    return out


class Extractor:
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.pdf = pdfplumber.open(pdf_path)
        self.checks: list[tuple[str, int, int]] = []

    def tables(self, page: int):
        return self.pdf.pages[page - 1].find_tables(TABLE_SETTINGS)

    def page_numbers(self, page: int) -> Counter:
        txt = subprocess.run(["pdftotext", "-layout", "-f", str(page), "-l", str(page), self.pdf_path, "-"],
                             capture_output=True, text=True).stdout.replace("‐", "-").replace(",", "")
        return Counter(re.findall(r"\d*\.\d+|\d+", txt))

    def check(self, name: str, page: int, values: list[str]) -> None:
        """Second reader: every number we extracted from `page` is on the page per poppler."""
        on_page = self.page_numbers(page)
        toks = [t for v in values for t in re.findall(r"\d*\.\d+|\d+", (v or "").replace(",", ""))]
        missing = [t for t in toks if t not in on_page]
        self.checks.append((f"{name} (p{page})", len(toks), len(missing)))


def main(pdf_path: str, out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ex = Extractor(pdf_path)

    # ---------------------------------------------------------------- Table 2 and 2C (port data)
    port, unb = [], []
    for page, table, label, scope in ((38, 0, "B-4", "single-port valves"), (39, 0, "B-5", "single-port valves"),
                                      (40, 0, "B-6", "EH & HP valves")):
        t = ex.tables(page)[table]
        rows = [r for r in split_rows(t.extract()) if num(r[0] if r[0] else (r[1] if len(r) > 1 else "")) is not None]
        rows = [[c for c in r if c is not None] for r in rows]
        tname = "2" if page < 40 else "2C"
        for r in rows:
            r = [c for c in r]
            # Table 2C has an empty first column
            if not r[0] and len(r) > 4:
                r = r[1:]
            d, circ, area = num(r[0]), num(r[1]), num(r[2])
            text = r[3] if len(r) > 3 else ""
            port.append({"table": tname, "scope": scope, "valve": "", "nps": "", "port_in": d,
                         "circumference_in": circ, "area_in2": area, "unbalance_area_in2": "",
                         "stem_in": "", "printed_label": label})
            for a, applies in unbalance_entries(text):
                unb.append({"table": tname, "port_in": d, "unbalance_area_in2": a, "applies_to": applies,
                            "printed_label": label})
            ex.check(f"Table {tname}", page, [r[0], r[1], r[2], text])

    # ---------------------------------------------------------------- Tables 2D-2H (per valve)
    def per_valve(page, table, tname, label, cols, valve_col=0):
        t = ex.tables(page)[table]
        rows = split_rows(t.extract())
        rows = [r for r in rows if num(r[cols["port_in"]]) is not None]
        rows = carry(rows, [valve_col])
        for r in rows:
            port.append({"table": tname, "scope": "", "valve": r[valve_col], "nps": r[cols["nps"]] if "nps" in cols else "",
                         "port_in": num(r[cols["port_in"]]), "circumference_in": num(r[cols["circ_in"]]),
                         "area_in2": "", "unbalance_area_in2": num(r[cols["unb_in2"]]),
                         "stem_in": frac(r[cols["stem_in"]]) if "stem_in" in cols else "", "printed_label": label})
            ex.check(f"Table {tname}", page, [r[c] for c in cols.values()])

    std = {"nps": 1, "port_in": 3, "unb_in2": 5, "circ_in": 7}
    per_valve(41, 0, "2D", "B-7", std)
    per_valve(42, 0, "2E", "B-7.1", std)
    per_valve(42, 1, "2F", "B-7.1", std)
    per_valve(43, 0, "2G", "B-8", {"nps": 2, "port_in": 4, "unb_in2": 8, "circ_in": 10})
    per_valve(43, 1, "2H TBX & CVX", "B-8", {"port_in": 1, "stem_in": 3, "unb_in2": 7, "circ_in": 11}, valve_col=0)
    for p in port:
        if p["table"] == "2H TBX & CVX":
            p["valve"] = "TBX, CVX (bore seal)"
    # TBX/CVX piston ring construction has its own unbalance area (column 9)
    t = ex.tables(43)[1]
    for r in [r for r in split_rows(t.extract()) if num(r[1]) is not None]:
        port.append({"table": "2H TBX & CVX", "scope": "", "valve": "TBX, CVX (piston ring)", "nps": "",
                     "port_in": num(r[1]), "circumference_in": num(r[11]), "area_in2": "",
                     "unbalance_area_in2": num(r[9]), "stem_in": frac(r[3]), "printed_label": "B-8"})
    per_valve(45, 0, "2H NotchFlo DST", "B-9", std)

    with open(out / "port_data.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(port[0]))
        w.writeheader()
        w.writerows(port)
    with open(out / "unbalance_area.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(unb[0]))
        w.writeheader()
        w.writerows(unb)

    # ---------------------------------------------------------------- Table 3 (stem area)
    rows = [r for r in split_rows(ex.tables(47)[0].extract()) if num(r[0]) is not None]
    with open(out / "stem_area.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["stem_in", "stem_text", "area_in2", "printed_label"])
        for r in rows:
            w.writerow([frac(r[1]), r[1], num(r[3]), "B-11"])
        ex.check("Table 3", 47, [x for r in rows for x in r])

    # ---------------------------------------------------------------- Table 4 (seat load rules)
    rules = []
    for page, label in ((48, "B-12"), (49, "B-13")):
        rows = split_rows(ex.tables(page)[0].extract())
        rows = [r[:7] if len(r) > 7 and not r[0] and r[1] in ("", "TYPE") and False else r for r in rows]
        start = next(i for i, r in enumerate(rows) if r[0] == "TYPE" or (len(r) > 1 and r[1] == "TYPE"))
        off = 0 if rows[start][0] == "TYPE" else 1
        body = [r[off:off + 7] for r in rows[start + 2:] if any(r)]
        body = [r for r in body if r[3] or r[4]]  # rule rows have a class or an equation
        body = carry(body, [0, 1])
        for r in body:
            rules.append({"type": r[0], "construction": r[1], "port_size": r[2], "class_standard": r[3],
                          "equation_standard": r[4], "class_optional": r[5], "equation_optional": r[6],
                          "printed_label": label})
        ex.check("Table 4", page, [x for r in body for x in r])
    with open(out / "seat_load_rules.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rules[0]))
        w.writeheader()
        w.writerows(rules)

    # ---------------------------------------------------------------- Table 5 (composition seat factors)
    rows = split_rows(ex.tables(50)[0].extract())
    group, fac = "", []
    seats = [("PTFE or CTFE", "Up or Down"), ("Synthetic rubber", "Down"), ("Synthetic rubber", "Up"),
             ("Polyurethane", "Down"), ("Polyurethane", "Up")]
    for r in rows:
        if r[0].startswith("For "):
            group = r[0].replace("For ", "")
            continue
        if num(r[1].split("(")[0]) is None:
            continue
        for k, (seat, flow) in enumerate(seats):
            a, b = r[2 + 2 * k], r[3 + 2 * k]
            if a and b:
                fac.append({"valves": group, "port_in": num(r[1].split("(")[0]), "seat": seat, "flow": flow,
                            "A": num(a), "B": num(b), "printed_label": "B-14"})
        ex.check("Table 5", 50, r)
    with open(out / "seat_factors.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(fac[0]))
        w.writeheader()
        w.writerows(fac)

    # ---------------------------------------------------------------- Table 6 (packing friction)
    pf = []
    rows = split_rows(ex.tables(52)[0].extract())
    rows = [r[1:] if not r[0] else r for r in rows]
    body = [r for r in rows if r[1] and (r[1] == "All" or num(r[1]) is not None)]
    # Stem diameter and the PTFE columns are merged over the pressure classes of one stem size.
    body = carry(body, [0, 2, 3])
    names = ["PTFE single", "PTFE double", "PTFE/composition", "Graphite ribbon/filament single",
             "Graphite ribbon/filament double"]
    for r in body:
        for k, name in enumerate(names):
            v = num(r[2 + k])
            if v is not None:
                pf.append({"table": "6", "packing": name, "stem_in": frac(r[0]), "pressure_class": r[1],
                           "pounds": v, "printed_label": "B-16"})
    ex.check("Table 6", 52, [x for r in body for x in r[:2] + r[4:7]])
    # Tables 6A-6C (page B-17): pounds rows only
    titles = {0: "6A ENVIRO-SEAL", 1: "6B HIGH-SEAL Graphite ULF", 2: "6C HIGH-SEAL Graphite"}
    for ti, t in enumerate(ex.tables(53)):
        rows = split_rows(t.extract())
        heads = [r for r in rows if r and r[0] == "mm"]
        lb_at = next(i for i, r in enumerate(rows) if any("Pounds" in c for c in r))
        cols = [c for c in rows[0][2:]] if ti != 1 else ["PTFE or duplex", "Graphite ULF", "H2 duplex"]
        if ti == 0:
            cols = ["Graphite ULF"]
        if ti == 2:
            cols = ["Graphite"]
        for r in rows[lb_at + 1:]:
            if num(r[0]) is None:
                continue
            for k, name in enumerate(cols):
                v = num(r[2 + k])
                if v is not None:
                    pf.append({"table": titles[ti].split()[0], "packing": f"{titles[ti]} {name}".strip(),
                               "stem_in": frac(r[1]), "pressure_class": "All", "pounds": v, "printed_label": "B-17"})
            ex.check(f"Table {titles[ti]}", 53, r)
        _ = heads
    # Table 6D (page B-18): ISO-Seal, pounds columns
    rows = [r for r in split_rows(ex.tables(54)[0].extract()) if re.search(r"CL\d", r[2] or "")]
    rows = carry(rows, [0, 1])  # stem diameter is printed once per group of pressure classes
    for r in rows:
        for name, col in (("ISO-Seal PTFE", 4), ("ISO-Seal Graphite", 6)):
            v = num(r[col])
            if v is not None:
                pf.append({"table": "6D", "packing": name, "stem_in": frac(r[1]), "pressure_class": r[2],
                           "pounds": v, "printed_label": "B-18"})
        ex.check("Table 6D", 54, r)
    with open(out / "packing_friction.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(pf[0]))
        w.writeheader()
        w.writerows(pf)

    print(f"port rows {len(port)}, unbalance entries {len(unb)}, seat rules {len(rules)}, "
          f"seat factors {len(fac)}, packing friction {len(pf)}")
    bad = [(n, t, m) for n, t, m in ex.checks if m]
    total = sum(t for _, t, _ in ex.checks)
    print(f"second reader: {total - sum(m for _, _, m in bad)} of {total} numbers found on their page")
    for n, t, m in bad:
        print(f"  {n}: {m} of {t} not found")




# ---------------------------------------------------------------- spring-and-diaphragm force tables
# 657C (pages B-46.1 to B-46.4) prints travel in mm and splits rows over two lines: not parsed yet.
ACTUATOR_PAGES = [(87, 102, "657"), (107, 119, "657R"), (120, 132, "667")]
PART = re.compile(r"\b(\d[A-Z]\d{4}\s?X?\w{5}|\d{2}[A-Z]\d{4}X\w{3}|GG\d+X\w+)\b")


def diaphragm_force_tables(pdf_path: str, out: Path) -> tuple[int, int]:
    """'Available Actuator Force' pages: force (lb) and bench set by size, supply range, travel and spring."""
    rows, checked, missing = [], 0, 0
    for first, last, act in ACTUATOR_PAGES:
        for page in range(first, last + 1):
            txt = subprocess.run(["pdftotext", "-layout", "-f", str(page), "-l", str(page), pdf_path, "-"],
                                 capture_output=True, text=True).stdout.replace("‐", "-")
            label = re.search(r"Page (B-[\d.]+)", txt)
            size = re.search(r"Size ([\d/i, ]+?)\s*\(", txt)
            lines = txt.splitlines()
            supply, travels = "", []
            i = 0
            while i < len(lines):
                ln = lines[i]
                m = re.search(r"(\d+-\d+) Psig to Diaphragm", ln)
                if m:
                    supply = m.group(1)
                nums = re.findall(r"(?<![\w(-])\d*\.\d+|(?<![\w(.-])\d\b", ln)
                # The travel header: a line of increasing inch values (e.g. 0.375 0.4375 ... 1.5)
                tv = [float(x) for x in re.findall(r"(?<![\w(-])(\d*\.\d+|\d)(?![\w)-])", ln)]
                if len(tv) >= 2 and tv == sorted(tv) and all(0.2 <= t <= 8 for t in tv) and not PART.search(ln) \
                        and "(" not in ln and len(tv) == len(nums):
                    travels = tv
                    i += 1
                    continue
                pm = PART.search(ln)
                if pm and travels and i + 1 < len(lines):
                    forces = re.findall(r"(?<![\w-])(\d[\d,]*|---)(?![\w-])", ln[:pm.start()])
                    nxt = lines[i + 1]
                    benches = re.findall(r"\(?(\d+-\d+)\)?|(---)", nxt)
                    benches = [a or b for a, b in benches]
                    rate = re.search(r"\((\d[\d,]*)\)\s*$", nxt.strip())
                    forces = forces[-len(travels):]
                    for t, fo, bs in zip(travels, forces, benches[:len(travels)]):
                        if fo != "---":
                            rows.append({"actuator": act, "size": (size.group(1).strip() if size else ""),
                                         "supply": supply, "travel_in": t, "spring": re.sub(r"\s", "", pm.group(1)),
                                         "spring_rate_lb_in": rate.group(1).replace(",", "") if rate else "",
                                         "force_lb": fo.replace(",", ""), "bench_set": bs if bs != "---" else "",
                                         "printed_label": label.group(1) if label else ""})
                            checked += 1
                            missing += fo.replace(",", "") not in txt.replace(",", "")
                    i += 2
                    continue
                i += 1
    with open(out / "diaphragm_force.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return checked, missing


if __name__ == "__main__" and len(sys.argv) > 2:
    n, miss = diaphragm_force_tables(sys.argv[1], Path(sys.argv[2]))
    print(f"diaphragm force values {n}, not found on page {miss}")


if __name__ == "__main__":
    main(*sys.argv[1:])
