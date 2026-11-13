"""Typed actuator torque output for rotary actuators in Catalog 14 section D (1051, 1052, 1061, 1068, 2052).

Reads data/catalog14/table_values.csv and classifies each value by actuator, the valves the page says it is
used with, flow direction, actuator size, air supply / diaphragm pressure range, spring, initial spring
compression, action (PDTC / PDTO, spring-to-close / air-to-close, double acting), what the number is, and
the angle of rotation it applies at:

    TB                 breakout torque available (TB_SEATING / TB_UNSEATING where printed separately)
    TD                 dynamic torque available at an angle of rotation
    TD_MAX_ROTATION    dynamic torque at a maximum rotation (60, 75 or 90 degrees: travel stops)
    TORQUE             torque at an angle (1052 net/spring output tables, 1068 spring-return tables)
    BREAKOUT, SEATING, UNSEATING   1068 spring-return breakout / seating / unseating torque
    TORQUE_AT_SUPPLY   1068 double-acting torque at a supply pressure
    PER_PSIG           1061 torque per psig of cylinder pressure, at an angle pair (0 or 90, 10 or 80 ...)
    MAX_CYLINDER_PSIG  1061 maximum allowable cylinder pressure
    SPLINE_LIMIT       1061 valve shaft spline torque limits

Torques are lbf-in (the 1068 Nm table is kept with unit 'N-m').

Writes data/catalog14/torque/actuator_torque.csv.

Usage:
    python extract/catalog14_actuator_torque.py data/catalog14
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path


def label_key(label: str) -> tuple[int, int]:
    m = re.match(r"D-(\d+)(?:\.(\d+))?", label)
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)


def clean(c: str) -> str:
    c = c.replace("(cid:2)", "").replace("_", "").replace("‐", "-")
    c = re.sub(r"\((\d)\)", "", c)
    c = re.sub(r"(\w)- (\w)", r"\1\2", c)  # words hyphenated across lines: "ACTU- ATOR", "Com- pression"
    return re.sub(r"\s+", " ", c).strip()


def angle_in(c: str) -> float | None:
    m = re.match(r"^(?:TD at |at )?(\d+(?:\.\d+)?)\s*(?:degrees?|degree rotation|rotation|closed|open)?$", c, re.I)
    return float(m.group(1)) if m else None


def flow_of(*texts: str) -> str:
    for t in texts:
        t = (t or "").lower()
        for f in ("forward", "reverse"):
            if f + " flow" in t:
                return f
    return ""


def first_key(keys: dict, pattern: str) -> str:
    return next((v for k, v in keys.items() if re.search(pattern, k, re.I)), "")


def classify(path: str, title: str) -> dict:
    comps = [clean(c) for c in path.split(" › ") if clean(c)]
    text = " | ".join(comps)
    d = {"action": "", "quantity": "", "angle_deg": None, "max_rotation_deg": None, "supply": "", "unit": "lbf-in"}
    m = re.search(r"\((PDTC|PDTO)\)", text) or re.search(r"\b(PDTC|PDTO)\b", title)
    if m:
        d["action"] = m.group(1)
    elif re.search(r"spring to close", title, re.I):
        d["action"] = "spring to close"
    elif re.search(r"air to close", title, re.I):
        d["action"] = "air to close"
    elif re.search(r"double acting", title, re.I):
        d["action"] = "double acting"
    m = re.search(r"(\d+(?:\.\d+)?) psi supply", text, re.I)
    if m:
        d["supply"] = m.group(1) + " psig"
    last = comps[-1] if comps else ""
    if re.search(r"initial com-? ?pres", text, re.I):
        d["quantity"] = "INITIAL_COMPRESSION_PSIG"
    elif re.match(r"actuator size", text, re.I):
        d["quantity"] = "SIZE"
    elif re.search(r"per psig cylinder pressure", text, re.I):
        d["quantity"] = "PER_PSIG"
        m = re.search(r"(\d+) or (\d+)$", last)
        d["angle_deg"] = float(m.group(1)) if m else None
    elif re.search(r"maximum allowable cylinder pressure", text, re.I):
        d["quantity"], d["unit"] = "MAX_CYLINDER_PSIG", "psig"
    elif re.search(r"spline torque limit", text, re.I):
        d["quantity"] = "SPLINE_LIMIT"
    elif re.match(r"torque \((nm|inlb)\) pressure", text, re.I):
        d["quantity"] = "TORQUE_AT_SUPPLY"
        d["unit"] = "N-m" if "(nm)" in text.lower() else "lbf-in"
        d["supply"] = last + (" barg" if d["unit"] == "N-m" else " psig")
    elif re.search(r"\bTB\b|\bTb\b", text):
        sub = [c for c in comps if c.lower() in ("seating", "unseating")]
        d["quantity"] = "TB_" + sub[0].upper() if sub else "TB"
    elif re.search(r"\bTD\b|\bT[ns] OPEN\b", text):
        a = next((angle_in(c) for c in comps[1:] if angle_in(c) is not None), None)
        mr = re.search(r"(\d+) maximum rotation", text, re.I)
        if mr:
            d["quantity"], d["max_rotation_deg"] = "TD_MAX_ROTATION", float(mr.group(1))
        else:
            d["quantity"], d["angle_deg"] = "TD", a
    elif re.search(r"break-? ?out", last, re.I):
        d["quantity"] = "BREAKOUT"
    elif last.upper() in ("SEATING", "UNSEATING"):
        d["quantity"] = last.upper()
    elif re.search(r"degrees of valve rotation|torque \(inlb\)", text, re.I) and angle_in(last) is not None:
        d["quantity"], d["angle_deg"] = "TORQUE", angle_in(last)
    else:
        d["quantity"] = "other"
    return d


def main(c14_dir: str) -> None:
    base = Path(c14_dir)
    rows = [r for r in csv.DictReader(open(base / "table_values.csv", encoding="utf-8")) if r["section"] == "D"]
    rows.sort(key=lambda r: (label_key(r["printed_label"]), int(r["table"]), int(r["row"])))
    current = {"actuator": "", "used_with": "", "page": None}
    tables: dict[tuple, list] = {}
    for r in rows:
        k = label_key(r["printed_label"])
        if not ((k >= (123, 0)) or (r["printed_label"] in ("D-111", "D-112"))):
            continue
        tables.setdefault((r["page"], r["table"]), []).append(r)
    out, stats = [], Counter()
    for (page, table), recs in sorted(tables.items(), key=lambda kv: (label_key(kv[1][0]["printed_label"]), int(kv[0][1]))):
        r0 = recs[0]
        segs = [s.strip() for s in r0["heading"].split(" | ") if s.strip()]
        # the title is above the table, or inside its ruled box (then the converter kept it as the row group)
        title = next((t for t in [r0["caption"]] + [x["group"] for x in recs] if re.match(r"table \d", t, re.I)), "")
        if r0["printed_label"] in ("D-111", "D-112"):  # actuator tables on the V150/V200/V300 attenuator pages
            m = re.search(r"(1052|2052)", title + " " + " ".join(x["column"] for x in recs[:3]))
            actuator = m.group(1) if m else ("1052" if r0["printed_label"] == "D-111" else "2052")
            used_with = "V150, V200, and V300 with Attenuator"
        else:
            m = re.match(r"^(\d{4})\b", segs[0]) if segs else None
            if m:
                current["actuator"] = m.group(1)
                current["used_with"] = next((s for s in segs if s.lower().startswith("used with")), "")
                current["used_with"] = re.sub(r"^used with\s*", "", current["used_with"], flags=re.I)
                if not current["used_with"] and re.search(r"all valves", " ".join(segs), re.I):
                    current["used_with"] = "All Valves"
            actuator, used_with = current["actuator"], current["used_with"]
            # 1068 tables name the valve in their title ("Table 1. CV500 Torque, Spring to Close")
            m = (re.match(r"table \d+\.\s*(.+?) actuator,", title, re.I)
                 or re.match(r"table \d+\.\s*(.+?) (?:valve )?torque", title, re.I))
            if m and actuator == "1068":
                used_with = m.group(1)
        flow = flow_of(title, r0["heading"], r0["caption"])
        by_row: dict[str, list] = {}
        for r in recs:
            by_row.setdefault(r["row"], []).append(r)
        for row_no, cells in by_row.items():
            keys = json.loads(cells[0]["keys"])
            attrs = {"size": first_key(keys, r"^(actua-? ?tor )?size$"), "spring": first_key(keys, r"spring"),
                     "diaphragm_psig": first_key(keys, r"air to dia"),
                     "max_rotation_key": first_key(keys, r"maximum rotation"),
                     "valve_nps": first_key(keys, r"valve size")}
            init = ""
            for c in cells:
                q = classify(c["column"], title)
                if q["quantity"] == "SIZE" and c["value"]:
                    attrs["size"] = attrs["size"] or c["value_raw"]
                if q["quantity"] == "INITIAL_COMPRESSION_PSIG" and c["value"]:
                    init = c["value"]
            for c in cells:
                if not c["value"]:
                    continue
                q = classify(c["column"], title)
                if q["quantity"] in ("SIZE", "INITIAL_COMPRESSION_PSIG"):
                    continue
                stats[q["quantity"]] += 1
                out.append({
                    "actuator": actuator, "used_with": used_with, "flow": flow, "size": attrs["size"],
                    "diaphragm_psig": attrs["diaphragm_psig"], "supply": q["supply"], "spring": attrs["spring"],
                    "initial_compression_psig": init, "action": q["action"], "quantity": q["quantity"],
                    "angle_deg": "" if q["angle_deg"] is None else q["angle_deg"],
                    "max_rotation_deg": q["max_rotation_deg"] or attrs["max_rotation_key"] or "",
                    "valve_nps": attrs["valve_nps"], "value": c["value"], "unit": q["unit"],
                    "value_raw": c["value_raw"], "table_title": title, "printed_label": c["printed_label"],
                    "page": page, "table_no": table, "row_no": row_no, "column_path": c["column"],
                    "confirmed": c["confirmed"], "merged": c["merged"]})
    with open(base / "torque" / "actuator_torque.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f"{len(out)} actuator torque values for {sorted({r['actuator'] for r in out})}: {dict(stats)}")


if __name__ == "__main__":
    main(*sys.argv[1:])
