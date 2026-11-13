"""Typed torque-method factors for every rotary valve in Catalog 14 section D (pages D-4 to D-122.3).

Reads data/catalog14/table_values.csv (every section D cell, typed, with row keys and column paths) and
classifies each value as one of:
    A, B        breakout torque TB = A (dP shutoff) + B
    C           dynamic torque TD = C (dP eff), at an angle of rotation
    K           effective pressure drop for gas, dP eff = K x P1 abs, at an angle of rotation
    MAST        maximum allowable shaft torque (lbf-in), optionally per shaft material or bearing
    E, F        SIS ball valve factors (page D-98)
    BREAK, RUN  Z500 break and run torque factors (page D-122.1)
    VRUN, VETC, VBTO   30,000 valve operating torques at a pressure drop (pages D-29 to D-29.6)
    STRENGTH    shaft material relative strength by temperature (percent of MAST)
with the valve (from the catalog's table of contents), pressure class, flow direction, construction
(seal / packing / bearing row group), size, shaft, angle and any other qualifier from the column path.

Values outside these patterns are kept with factor 'other' so nothing is dropped silently.

Writes data/catalog14/torque/torque_factors.csv.

Usage:
    python extract/catalog14_torque_factors.py data/catalog14
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

# Table of contents, page D-1: where each valve's pages start (actuator sections excluded).
TOC = [("D-4", "7600"), ("D-10", "8532"), ("D-16", "8560"), ("D-24", "8580"), ("D-26.1", "8590"),
       ("D-27", "9500"), ("D-29", "30,000"), ("D-29.4", "30,000 Cryogenic"), ("D-30", "A11"),
       ("D-57", "A31A"), ("D-63", "A31A Cryogenic"), ("D-71", "A31D"), ("D-83", "Bettis G"),
       ("D-87", "Control-Disk"), ("D-91", "Control-Disk NPS 14-36"), ("D-93.1", "CL600 Control-Disk"),
       ("D-94", "FieldQ"), ("D-98", "SIS"), ("D-99", "CV500"), ("D-100", "Three-Way Butterfly"),
       ("D-102", "U"), ("D-104", "V100"), ("D-106", "V150/V200/V300"), ("D-115", "V250"),
       ("D-117", "V260"), ("D-120", "V270"), ("D-120.2", "V280"), ("D-120.4", "V500"),
       ("D-122.1", "Z500"), ("D-123", None)]


def label_key(label: str) -> tuple[float, ...]:
    m = re.match(r"D-(\d+)(?:\.(\d+))?", label)
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)


def valve_for(label: str) -> str | None:
    found = None
    for start, valve in TOC:
        if label_key(label) >= label_key(start):
            found = valve
    return found


ANGLE_HEAD = re.compile(r"angle|rotation|degree|travel \(degrees\)", re.I)
MAST_HEAD = re.compile(r"maximum allowable|max(imum)? torque|\bmast\b|max torque", re.I)
K_TABLE = re.compile(r"k[\s-]*values?|k factor|effective pressure drop", re.I)
C_TABLE = re.compile(r"c factor|\(c factor\)|c factors|dynamic torque", re.I)
UNIT = re.compile(r"^\(?(lbf?[\s·-]*in(ch)?|in[\s·-]*lbf?|inlbf|lbfin|lbfinch|in-lbs|\(lbfin\)|\(inlbf\)|value|"
                  r"degrees?|psi|psid|\(\))\)?$", re.I)


def clean(comp: str) -> str:
    comp = comp.replace("(cid:2)", "").replace("_", "").replace("°", "")
    comp = re.sub(r"\((\d)(,\d)*\)", "", comp)  # footnote marks
    return re.sub(r"\s+", " ", comp).strip()


def angle_of(comp: str) -> float | None:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(degrees?|deg|\(\)|\([KΚθ]\))?", clean(comp), re.I)
    return float(m.group(1)) if m else None


# Page D-10 legend: K (kappa) = valve torque tends to close the valve; θ = beyond this degree of opening the
# valve torque tends to open the valve.
DIRECTION = {"K": "tends to close", "Κ": "tends to close", "θ": "tends to open"}


def direction_in(comps: list[str]) -> str:
    for c in comps:
        m = re.search(r"\(([KΚθ])\)$", c)
        if m:
            return DIRECTION[m.group(1)]
    return ""


def flow_of(*texts: str) -> str:
    for t in texts:
        t = t.lower()
        if "forward and reverse" in t:
            return "forward and reverse"
        for f in ("forward", "reverse", "normal"):
            if f + " flow" in t:
                return f
    return ""


def pressure_class(heading: str, title: str = "") -> str:
    m = re.match(r"((?:Cryogenic )?CL\s?\d+(?:/\d+)?)\b", title or "")
    if m:
        return m.group(1)  # a table title naming the class, e.g. "CL300 K Values ..." (page D-10)
    for seg in heading.split(" | "):
        if re.search(r"\bCL\s?\d|\bPN\s?\d", seg):
            return seg.strip()
    return ""


def variant_of(heading: str) -> str:
    """Heading segments that qualify the valve (e.g. 'with Attenuator', 'Novex Seal'): the short segments
    after the valve name, up to the first piece of procedure text printed beside the table."""
    keep = []
    for x in [x.strip() for x in heading.split(" | ")[1:]]:
        if re.search(r"\bCL\s?\d|\bPN\s?\d|\bflow\b|^\(", x, re.I):
            continue  # pressure class and flow direction have their own columns
        if (len(x) > 40 or not x or (x[0].islower() and not x.startswith("with ")) or not x[0].isalpha()
                or re.search(r"[=:]|\.$|\beff\b|k values|torques?\b|liquid|gas only|vee-ball|formula|\buse\b|"
                             r"maximum|\bif\b|calculate|requirements|1abs", x, re.I)):
            break
        keep.append(x)
    return " | ".join(keep[:2])


def split_keys(keys: dict) -> tuple[str, str, dict]:
    nps = shaft = ""
    rest = {}
    for k, v in keys.items():
        kl = k.lower()
        if not nps and (re.search(r"valve (body )?size|\bnps\b|^bore$", kl) and "shaft" not in kl):
            nps = v
        elif re.search(r"shaft|keyed|spline|dia", kl) and "material" not in kl:
            shaft = f"{shaft}; {k}: {v}" if shaft else (v if re.search(r"shaft", kl) else f"{k}: {v}")
        else:
            rest[k] = v
    return nps, shaft, rest


def classify(path: str, table_text: str, has_abc: bool, has_mast: bool = False) -> tuple[str, float | None, str]:
    comps = [clean(c) for c in path.split(" › ") if clean(c)]
    letters = [c for c in comps if re.fullmatch(r"[ABCKEF]", c)]
    angle = next((angle_of(c) for c in comps if angle_of(c) is not None), None)
    first = comps[0] if comps else ""
    if re.search(r"multiplier", table_text.split(" | ")[0], re.I):
        return "MULTIPLIER", None, " › ".join(comps)  # U valve torque multipliers for non-standard travel
    if re.search(r"relative strength", table_text, re.I) or re.match(r"temperature", first, re.I):
        factor = "STRENGTH"
        angle = None
    elif first.upper() in ("VRUN", "VETC", "VBTO") or (comps and comps[-1].upper() in ("VETC", "VBTO")):
        factor = comps[-1].upper()
        angle = None
    elif re.match(r"break torque", first, re.I):
        factor = "BREAK"
    elif re.match(r"run torque", first, re.I):
        factor = "RUN"
    elif first in ("SF", "FF"):
        factor = first  # SIS service and fluid factors (page D-98.3)
    elif re.match(r"margin factor", first, re.I):
        factor = "MARGIN"
    elif any(MAST_HEAD.search(c) for c in comps) or (re.search(r"\bMAST\b", table_text) and not letters):
        factor = "MAST"
        angle = None  # an angle in a MAST path is a header spread from the C columns
    elif letters:
        factor = letters[0]
        if factor in ("A", "B"):
            angle = None
    elif re.match(r"c factor|c\(", first, re.I) or (first == "C"):
        factor = "C"
    elif ANGLE_HEAD.search(first) or angle is not None or K_TABLE.search(first) or C_TABLE.search(first):
        title_text = table_text.split(" | ")[0] + " " + first  # the table's own title and header first
        if C_TABLE.search(title_text) or has_mast:
            factor = "C"  # a C-factor table, or angle columns printed beside the shaft limit
        elif K_TABLE.search(title_text):
            factor = "K"
        else:
            factor = "K"  # angle columns with no A/B/C: K values (page D-10: dP eff = K x P1 abs for gas)
    else:
        factor = "other"
    qual = [c for c in comps if c != factor and angle_of(c) is None and not UNIT.match(c)
            and not (factor in "CK" and (ANGLE_HEAD.search(c) or K_TABLE.search(c) or C_TABLE.search(c)))
            and not (factor == "MAST" and MAST_HEAD.search(c))
            and not (factor == "STRENGTH" and re.match(r"temperature", c, re.I))]
    if factor == "STRENGTH":
        qual = [c for c in comps if not re.match(r"temperature", c, re.I)]
    return factor, angle, " › ".join(qual)


def main(c14_dir: str) -> None:
    base = Path(c14_dir)
    titles = {}
    for t in csv.DictReader(open(base / "index.csv", encoding="utf-8")):
        m = re.match(r".+?_t(\d+)", t["id"])
        titles[(t["page"], m.group(1))] = t["title"]
    every = [r for r in csv.DictReader(open(base / "table_values.csv", encoding="utf-8")) if r["section"] == "D"]
    marks = {}  # (page, table, row, angle) -> direction, from θ / K cells beside the C factors
    for r in every:
        if r["value_raw"] in DIRECTION:
            a = next((angle_of(c) for c in r["column"].split(" › ") if angle_of(c) is not None), None)
            marks[(r["page"], r["table"], r["row"], a)] = DIRECTION[r["value_raw"]]
    rows = [r for r in every if r["value"] != ""]
    by_table: dict[tuple, list] = {}
    for r in rows:
        by_table.setdefault((r["page"], r["table"]), []).append(r)
    out, stats = [], Counter()
    for (page, table), recs in by_table.items():
        label = recs[0]["printed_label"]
        valve = valve_for(label)
        if not valve or valve in ("Bettis G", "FieldQ"):
            continue  # actuator torque output: see catalog14_actuator_torque.py
        heading = recs[0]["heading"]
        cap = recs[0].get("caption", "")
        if not re.match(r"^(table \d|(cryogenic )?cl\s?\d[\d/]*\s.*(k values|characteristics|torque))", cap, re.I):
            cap = ""  # the line above was a page header, a footnote or the previous table's last row
        title = titles.get((page, table), "") or cap
        if re.search(r"sample", title, re.I) or any("KM value" in r["keys"] for r in recs):
            continue  # sample calculations (D-114)
        if re.search(r"actuator", title, re.I) or any(re.search(r"PUSH-DOWN|ACTUATOR SIZE", r["column"]) for r in recs):
            continue  # an actuator torque table printed on a valve page (D-111, D-112)
        shaft_by_row = {r["row"]: r["value_raw"] for r in recs if re.match(r"shaft diameter", r["column"], re.I)}
        recs = [r for r in recs if not re.match(r"shaft diameter", r["column"], re.I)]
        has_mast = any(MAST_HEAD.search(r["column"]) for r in recs)
        has_abc = any(re.fullmatch(r"[ABC](\(\d\))?", clean(r["column"].split(" › ")[0])) for r in recs)
        for r in recs:
            keys = json.loads(r["keys"])
            text = " | ".join([title, r["group"], heading])
            factor, angle, qual = classify(r["column"], text, has_abc, has_mast)
            direction = direction_in(r["column"].split(" › ")) or marks.get((page, table, r["row"], angle), "")
            nps, shaft, rest = split_keys(keys)
            shaft = shaft or shaft_by_row.get(r["row"], "")  # SIS: shaft diameter printed as a column
            # A key named like an angle ("10" in D-118 table 5): the header's first angle became a key
            for k in list(rest):
                if angle_of(k) is not None and factor in ("K", "C"):
                    v = rest.pop(k)
                    if re.fullmatch(r"-?[\d.]+", v):
                        out.append(dict(valve=valve, variant=variant_of(heading), pressure_class=pressure_class(heading, title),
                                        flow=flow_of(r["group"], title, heading), construction=r["group"],
                                        nps=nps, shaft=shaft, factor=factor, angle_deg=angle_of(k),
                                        qualifier=qual, torque_direction="", other_keys="", value=v, value_raw=v,
                                        table_title=title, printed_label=label, page=page, table_no=table, row_no=r["row"],
                                        column_path=k, confirmed=r["confirmed"], merged="0"))
            if "TRAVEL (DEGREES)" in keys and angle is None:
                angle = angle_of(keys["TRAVEL (DEGREES)"])
                rest.pop("TRAVEL (DEGREES)", None)
            if keys.get("Torques") == "MAST" and factor in ("VRUN", "VETC", "VBTO"):
                if r.get("merged") == "1":
                    continue  # a 30,000 run torque printed once beside the Operating/MAST pair: not a limit
                factor = "MAST_" + factor
            rest.pop("Torques", None)
            if factor == "STRENGTH":
                angle = None
            out.append(dict(valve=valve, variant=variant_of(heading), pressure_class=pressure_class(heading, title),
                            flow=flow_of(r["group"], title, heading),
                            construction="" if re.match(r"table \d", r["group"], re.I) else r["group"],
                            nps=nps, shaft=shaft, factor=factor, angle_deg=angle, qualifier=qual,
                            torque_direction=direction if factor == "C" else "",
                            other_keys=json.dumps(rest, ensure_ascii=False) if rest else "",
                            value=r["value"], value_raw=r["value_raw"], table_title=title, printed_label=label, page=page,
                            table_no=table, row_no=r["row"], column_path=r["column"], confirmed=r["confirmed"],
                            merged=r.get("merged", "0")))
            stats[factor] += 1
    (base / "torque").mkdir(exist_ok=True)
    with open(base / "torque" / "torque_factors.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f"{len(out)} torque factors for {len({r['valve'] for r in out})} valves: {dict(stats)}")


if __name__ == "__main__":
    main(*sys.argv[1:])
