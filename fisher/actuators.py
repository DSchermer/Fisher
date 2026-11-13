"""Actuator selection from Fisher Catalog 14 (Actuator Sizing, D103428X012).

Pressure drop method tables:
  Section A  sliding-stem valves: maximum allowable shutoff ΔP by port, travel, yoke boss, actuator
             size and air pressure / bench set.
  Section C  rotary valves: maximum allowable ΔP by valve, size, opening angle, actuator size, supply
             pressure and spring.

Every value is as printed (data/catalog14/allowable_dp.csv). Sections B (force method) and D (torque
method) are available as printed tables through `tables()` / `table()`.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

C14_DIR = Path(__file__).resolve().parent.parent / "data" / "catalog14"


def _rows(name: str) -> list[dict]:
    with open(C14_DIR / name, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _size(text: str) -> float | None:
    """'2-1/2' -> 2.5, '3/4(3)' -> 0.75, '1.125' -> 1.125; first size only."""
    t = re.sub(r"\(\d+\)", "", text or "").strip()
    m = re.match(r"(\d+)-(\d+)/(\d+)|(\d+)/(\d+)|(\d+(?:\.\d+)?)", t)
    if not m:
        return None
    if m.group(1):
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    if m.group(4):
        return int(m.group(4)) / int(m.group(5))
    return float(m.group(6))


@dataclass
class Rating:
    """One maximum allowable pressure drop for one valve + actuator construction."""
    section: str
    page: int
    printed_label: str
    heading: str
    group: str
    keys: dict
    column_heading: str
    column: str
    unit: str
    value: float
    footnotes: str
    # Parsed for filtering
    actuator: str
    valve: str
    port_in: float | None
    travel_in: float | None
    valve_nps: float | None
    shaft_in: float | None
    angle_deg: float | None
    actuator_size: str
    action: str
    flow: str
    leakage: str
    balance: str
    confirmed: bool = True

    @property
    def source(self) -> str:
        return f"Fisher Catalog 14, page {self.printed_label} (PDF page {self.page})"

    def to_dict(self) -> dict:
        size = self.actuator_size or self.column.split(" › ")[0]
        return {"actuator": self.actuator, "valve": self.valve, "size": size,
                **{k: v for k, v in self.keys.items() if v},
                "condition": self.column, "max_dP": self.value, "unit": self.unit,
                "action": self.action, "flow": self.flow, "leakage": self.leakage, "balance": self.balance,
                "group": self.group, "footnotes": self.footnotes, "source": self.source}


def _actuator_number(size: str) -> int:
    """'45/45i' -> 45, '130(2)' -> 130."""
    m = re.match(r"\d+", size or "")
    return int(m.group()) if m else 0


def _find_key(keys: dict, pattern: str) -> str:
    return next((v for k, v in keys.items() if re.search(pattern, k, re.I)), "")


@lru_cache(maxsize=1)
def ratings() -> list[Rating]:
    out = []
    headings = {r["page"]: r["heading"] for r in _rows("pages.csv")}
    for r in _rows("allowable_dp.csv"):
        if r["value"] == "":
            continue
        keys = json.loads(r["keys"])
        heading, group = headings[r["page"]], r["group"]
        ctx = f"{heading} | {group} | {r['column_heading']}"
        if r["section"] == "A":
            actuator = heading.split("|")[0].strip()
            valve = ""
        else:
            m = re.match(r"(.+?)\s+with\s+(.+?)\s*Actuator", heading)
            valve, actuator = (m.group(1).strip(), m.group(2).strip()) if m else ("", "")
            actuator = re.sub(r"™", "", actuator)
        action = next((a for a in ("Push-Down-To-Open or Push-Down-To-Close", "Push-Down-To-Open",
                                   "Push-Down-To-Close", "Spring-To-Close", "Spring-To-Open")
                       if a.lower() in ctx.lower()), "")
        flow = "Reverse Flow" if "reverse flow" in ctx.lower() else "Forward Flow" if "forward flow" in ctx.lower() else ""
        leak = re.search(r"Class\s+([IV]+)", ctx)
        port = re.search(r"([\d.]+)[\s-]*Inch Port", group)  # "2.5 Inch Port", "7-Inch Port (ED, ...)"
        out.append(Rating(
            section=r["section"], page=int(r["page"]), printed_label=r["printed_label"], heading=heading,
            group=group, keys=keys, column_heading=r["column_heading"], column=r["column"], unit=r["unit"],
            value=float(r["value"]), footnotes=r["footnotes"], actuator=actuator, valve=valve,
            port_in=float(port.group(1)) if port else None,
            travel_in=_size(_find_key(keys, r"travel")),
            valve_nps=_size(_find_key(keys, r"valve")),
            shaft_in=_size(_find_key(keys, r"shaft")),
            angle_deg=_size(_find_key(keys, r"angle")),
            actuator_size=_find_key(keys, r"act\w*\s*size"),
            action=action, flow=flow, leakage=f"Class {leak.group(1)}" if leak else "",
            balance="Unbalanced" if "unbalanced" in heading.lower() else "Balanced" if "balanced" in heading.lower() else "",
            confirmed=r["confirmed"] == "1",
        ))
    return out


def _match(text: str, want: str | None) -> bool:
    return not want or want.lower() in text.lower()


def sliding_stem(dp_required: float, port_in: float, travel_in: float | None = None, *,
                 actuator: str | None = None, yoke_boss: str | None = None, balance: str | None = None,
                 leakage: str | None = None) -> list[Rating]:
    """Section A: constructions whose maximum allowable shutoff ΔP (psi) is at least `dp_required`.

    Sorted smallest actuator first, then lowest air pressure/bench-set column, as the catalog's
    procedure suggests (start with the smallest actuator and work up).
    """
    hits = [r for r in ratings() if r.section == "A" and r.unit == "psi" and r.value >= dp_required
            and r.port_in is not None and abs(r.port_in - port_in) < 1e-6
            and (travel_in is None or (r.travel_in is not None and abs(r.travel_in - travel_in) < 1e-6))
            and _match(r.actuator, actuator) and _match(r.balance, balance) and _match(r.leakage, leakage)
            and (not yoke_boss or yoke_boss == _find_key(r.keys, "yoke"))]
    return sorted(hits, key=lambda r: (r.actuator, _actuator_number(r.actuator_size), r.page, r.value))


def rotary(dp_required: float, valve: str, nps: float | str | None = None, *, angle_deg: float | None = None,
           actuator: str | None = None, text: str | None = None, flow: str | None = None,
           shaft_in: float | str | None = None) -> list[Rating]:
    """Section C: constructions whose maximum allowable ΔP (psi) at `angle_deg` (all listed angles if
    None) is at least `dp_required`. `valve` matches the start of the valve name (e.g. "V150", "8532").
    A few tables (e.g. CV500 on C-109) are listed by shaft size instead of valve size: pass `shaft_in`."""
    size = _size(str(nps)) if nps not in (None, "") else None
    shaft = _size(str(shaft_in)) if shaft_in not in (None, "") else None
    hits = [r for r in ratings() if r.section == "C" and r.unit == "psi" and r.value >= dp_required
            and r.valve.upper().startswith(valve.upper())
            and (size is None or r.valve_nps == size) and (shaft is None or r.shaft_in == shaft)
            and (angle_deg is None or r.angle_deg == angle_deg)
            and _match(r.actuator, actuator) and _match(r.flow, flow)
            and _match(f"{r.heading} {r.group} {r.column}", text)]
    return sorted(hits, key=lambda r: (r.actuator, r.page, r.angle_deg or 0, r.column))


def options() -> dict:
    """Values available for filtering: actuators and valves per section, port sizes."""
    rs = ratings()
    return {
        "sliding_stem_actuators": sorted({r.actuator for r in rs if r.section == "A"}),
        "sliding_stem_ports_in": sorted({r.port_in for r in rs if r.section == "A" and r.port_in}),
        "rotary_valves": sorted({r.valve.split(",")[0].split(" ")[0] for r in rs if r.section == "C" and r.valve}),
        "rotary_actuators": sorted({r.actuator for r in rs if r.section == "C" and r.actuator}),
    }


# ------------------------------------------------------------------ all tables as printed

@lru_cache(maxsize=1)
def tables() -> list[dict]:
    """Index of every Catalog 14 table: id, page, printed_label, section, heading, title, rows, columns."""
    return _rows("index.csv")


def table(table_id: str) -> tuple[list[str], list[list[str]]]:
    with open(C14_DIR / "tables" / f"{table_id}.csv", encoding="utf-8", newline="") as fh:
        data = list(csv.reader(fh))
    return data[0], data[1:]


def search_tables(text: str, section: str | None = None) -> list[dict]:
    """Tables whose page heading or title contains `text` (case-insensitive)."""
    t = text.lower()
    return [i for i in tables() if (not section or i["section"] == section.upper())
            and (t in i["heading"].lower() or t in i["title"].lower() or t in i["printed_label"].lower())]


# ------------------------------------------------------------------ pressure drop method rules (pages C-5 to C-7)

# Table 2, page C-5: angles of rotation at which the dP eff calculation is required (1052 and 1066 actuators).
REQUIRED_ANGLES = {("9500", 60): [60], ("9500", 90): [90], ("V150", 60): [60], ("V150", 90): [70],
                   ("V500", 60): [60], ("V500", 90): [60, 90]}

# Table 3, page C-5: dP eff = factor x P1 abs for the 9500 (gas, liquid) by maximum rotation and disk style.
DP_EFF_9500 = {(60, "fishtail"): (0.18, 0.60), (60, "conventional"): (0.20, 0.45),
               (90, "fishtail"): (0.09, 0.45), (90, "conventional"): (0.14, 0.35)}


def required_angles(valve: str, max_rotation: int) -> list[int] | None:
    """Page C-5 table 2: angles at which to check the pressure drop for the 9500, V150 and V500."""
    return REQUIRED_ANGLES.get((valve.upper().replace("V200", "V150").replace("V300", "V150"), int(max_rotation)))


def k_values_c14(valve: str, nps: float | str) -> dict:
    """K values for gas dP eff = K x P1 abs: table 4 (8532, V150; page C-6) and table 5 (V500; page C-7)."""
    want = _size(str(nps))
    out: dict = {}
    if valve.upper().startswith("V500"):
        tid = next(t["id"] for t in tables() if t["printed_label"] == "C-7")
        headers, rows = table(tid)
        for r in rows:
            if _size(r[0]) == want:
                for h, v in zip(headers[1:], r[1:]):
                    if v:
                        m = re.search(r"(Full|Reduced) Port Rotation (\d+)", h)
                        out.setdefault(f"{m.group(1).lower()} port", {})[int(m.group(2))] = float(v)
        return out
    tid = next(t["id"] for t in tables() if t["printed_label"] == "C-6")
    headers, rows = table(tid)
    angles = [int(re.search(r"(\d+)$", h).group(1)) for h in headers[1:]]
    block = ""
    for r in rows:
        if r[0].endswith("Valves") or r[0].startswith(("8532", "V150")):
            block = r[0]
            continue
        hit = (block.startswith("8532") or "8532" in headers[0]) and valve.startswith("8532") and r[0] == "All Sizes"
        hit = hit or (block.startswith("V150") and valve.upper()[:4] in ("V150", "V200", "V300") and _size(r[0]) == want)
        if hit:
            out["table 4"] = {a: float(v) for a, v in zip(angles, r[1:]) if v}
    return out


def effective_dp_c14(valve: str, max_rotation: int, service: str, p1_psig: float, *, disk: str | None = None,
                     k: float | None = None, km: float | None = None, rc: float | None = None,
                     pv_psia: float | None = None) -> tuple[float, str]:
    """Page C-5 table 3. 9500: factor x P1 abs by disk style. 8532, V150, V500: gas K x P1 abs;
    liquid Km (P1 abs - rc Pv) (Catalog 12 flashing and cavitating liquids procedure)."""
    p1abs = p1_psig + 14.7
    if valve.startswith("9500"):
        g, liq = DP_EFF_9500[(int(max_rotation), (disk or "").lower())]
        f = g if service == "gas" else liq
        return f * p1abs, f"{f:g} x P1abs (page C-5 table 3, 9500 {disk} disk, {max_rotation} deg)"
    if service == "gas":
        if k is None:
            raise ValueError("gas dP eff needs K (k_values_c14)")
        return k * p1abs, f"K={k:g} x P1abs (page C-5 table 3)"
    if None in (km, rc, pv_psia):
        raise ValueError("liquid dP eff needs km, rc and pv_psia")
    return km * (p1abs - rc * pv_psia), "Km (P1abs - rc Pv) (page C-5 table 3)"


def constructions_covered() -> list[dict]:
    """Page C-4 table 1: the valve constructions the pressure drop tables cover, as printed."""
    tid = next(t["id"] for t in tables() if t["printed_label"] == "C-4")
    headers, rows = table(tid)
    return [{"valve": r[0], "constructions": r[1], "note": r[2] if len(r) > 2 else ""} for r in rows]
