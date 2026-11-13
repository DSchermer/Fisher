"""Catalog 14 force method, piston actuators beyond the 585C springless (fisher.actuator_force):

  585C spring-biased, sizes 25 and 50 (pages B-19 to B-23)
  685 double-acting springless (page B-26, tables A and C)
  685SE spring-extend and 685SR spring-retract (pages B-27.1 to B-27.7, the catalog's own equations)
  785C double-acting springless (page B-27.8, tables 1 and 2)

Forces A, B, C, D are the valve body forces of fisher.force (A unbalance, B seat load, C packing friction,
D additional forces). Pressures psig, forces lb, lengths inches. Tables are read from the typed Catalog 14
values (data/catalog14/table_values.csv), so every number traces to its printed page.
"""
from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

C14 = Path(__file__).resolve().parent.parent / "data" / "catalog14" / "table_values.csv"


@lru_cache(maxsize=1)
def _values() -> list[dict]:
    with open(C14, encoding="utf-8", newline="") as fh:
        return [r for r in csv.DictReader(fh) if r["section"] == "B"]


def c14(label: str, table: int | None = None) -> list[dict]:
    """Typed values of one printed Catalog 14 table, keys decoded."""
    return [{**r, "keys": json.loads(r["keys"])} for r in _values()
            if r["printed_label"] == label and (table is None or r["table"] == str(table))]


def _f(x) -> float:
    return float(str(x).replace(",", ""))


@dataclass
class Check:
    actuator: str
    size: str
    passes: bool
    checks: dict = field(default_factory=dict)
    values: dict = field(default_factory=dict)
    source: str = ""


# ------------------------------------------------------------------ 585C spring-biased (B-19 to B-23)

CYLINDER_AREA_585C = {"25": 26.0, "50": 47.0}  # page B-19 step 3


def spring_table_585c() -> list[dict]:
    """585C actuator spring force table (page B-21): size, springs, rate, travel, force."""
    out = []
    for r in c14("B-21", 1):
        size = "50" if "SIZE 50" in r["group"] else "25"
        rate = re.search(r"(\d+) lb/in", r["column"])
        travel = re.sub(r"\(\d\)", "", next(iter(r["keys"].values())))
        springs = r["column"].split(" › ")[-2] if " › " in r["column"] else ""
        out.append({"size": size, "springs": springs.replace("SIZE 25", "").strip(), "rate_lb_in": float(rate.group(1)),
                    "travel_in": float(travel), "force_lb": _f(r["value"]), "printed_label": "B-21"})
    return out


def _spring_force(rows: list[dict], travel: float) -> float:
    """Force at a travel; between printed travels the spring is linear (force = F0 + rate x travel)."""
    exact = [r["force_lb"] for r in rows if abs(r["travel_in"] - travel) < 1e-9]
    if exact:
        return exact[0]
    f0 = next(r["force_lb"] for r in rows if r["travel_in"] == 0)
    return f0 + rows[0]["rate_lb_in"] * travel


def select_585c_spring_biased(*, a: float, b: float, c: float, d: float = 0.0, travel_in: float,
                              supply_psig: float, fail: str, pressure_tends_to: str,
                              max_stem_load_lb: float | None = None, size: str | None = None) -> list[Check]:
    """585C spring-biased with push-down-to-close valves (pages B-19 to B-22).

    fail='open': spring retracts the rod (585C). fail='closed': spring extends the rod (585CR).
    pressure_tends_to: 'open' or 'close'. Returns every spring with its checks; the catalog's choice is the
    lightest spring rate that passes (first passing entry per size).
    """
    pto = pressure_tends_to == "open"
    out = []
    table = spring_table_585c()
    for sz in ([size] if size else ["25", "50"]):
        ac = CYLINDER_AREA_585C[sz]
        for springs in sorted({r["springs"] for r in table if r["size"] == sz},
                              key=lambda s: next(r["rate_lb_in"] for r in table if r["springs"] == s and r["size"] == sz)):
            rows = [r for r in table if r["size"] == sz and r["springs"] == springs]
            f_t, f_0 = _spring_force(rows, travel_in), _spring_force(rows, 0.0)
            air = supply_psig * ac
            if fail == "open":
                chk = {"spring_at_travel_opens_valve": f_t >= (c + d - a if pto else c + d + a),
                       "spring_at_0_strokes_full_open": f_0 >= c + d,
                       "air_closes_valve": air - f_t >= (a + b + c + d if pto else b + c + d - a)}
                stem = air - f_t
            else:
                chk = {"spring_at_0_closes_and_seats": f_0 >= (b + c + d + a if pto else b + c + d - a),
                       "spring_at_0_strokes_closed": f_0 >= c + d,
                       "air_opens_valve": air - f_t >= c + d}
                stem = air + f_t
            if max_stem_load_lb is not None:
                chk["within_stem_load"] = stem <= max_stem_load_lb
            out.append(Check("585C" if fail == "open" else "585CR", sz, all(chk.values()), chk,
                             {"springs": springs, "rate_lb_in": rows[0]["rate_lb_in"], "spring_force_at_travel_lb": f_t,
                              "spring_force_at_0_lb": f_0, "air_force_lb": air, "stem_load_lb": stem},
                             "Fisher Catalog 14, pages B-19 to B-22"))
    return out


# ------------------------------------------------------------------ 685 springless (B-26)

def table_685() -> list[dict]:
    rows: dict[tuple, dict] = {}
    for r in c14("B-26", 1):
        k = (r["keys"]["ACTUATOR SIZE"], r["keys"]["STROKE"])
        d = rows.setdefault(k, {"size": k[0], "stroke": k[1].lower()})
        col = r["column"]
        if col.endswith("› lb") and "SUPPLY" in col:
            d["force_100psig_lb"] = _f(r["value"])
        elif col.endswith("› psig"):
            d["max_cylinder_psig"] = _f(r["value"])
        elif col.endswith("› lb") and "THRUST" in col:
            d["max_thrust_lb"] = _f(r["value"])
    return list(rows.values())


def select_685(required_lb: float, supply_psig: float, *, stroke: str = "push") -> list[Check]:
    """685 (page B-26 step 5): force available = table A force x supply / 100 psig."""
    out = []
    for r in sorted((r for r in table_685() if r["stroke"] == stroke), key=lambda r: int(r["size"])):
        avail = r["force_100psig_lb"] * supply_psig / 100
        chk = {"force_available_ge_required": avail >= required_lb,
               "supply_le_max_cylinder_pressure": supply_psig <= r["max_cylinder_psig"],
               "force_le_max_thrust": avail <= r.get("max_thrust_lb", math.inf)}
        out.append(Check("685", r["size"], all(chk.values()), chk, {"force_available_lb": avail, **r},
                         "Fisher Catalog 14, page B-26 table A"))
    return out


# ------------------------------------------------------------------ 685SE / 685SR (B-27.1 to B-27.7)

PF_PSI = 2.0  # average actuator friction, psi of supply (pages B-27.1 and B-27.3)
MAX_CYLINDER_PSIG_685S = 150.0


def table_685s() -> dict[str, dict]:
    """Table 2: piston and rod areas (in2) by actuator size."""
    out: dict[str, dict] = {}
    for r in c14("B-27.5", 1):
        size = r["keys"].get("Actuator Size")
        d = out.setdefault(size, {})
        if r["column"] == "Piston Area › in2":
            d["piston_in2"] = _f(r["value"])
        elif r["column"] == "Piston Rod Area › in2":
            d["rod_in2"] = _f(r["value"])
    return out


def springs_685s() -> list[tuple[float, float]]:
    """Table 3: (Ks lb/in, preload lb), the same for sizes 10 to 28."""
    rows: dict[str, dict] = {}
    for r in c14("B-27.6", 1):
        d = rows.setdefault(r["row"], {})
        d["ks" if r["column"].startswith("Ks") else "preload"] = _f(r["value"])
    return sorted((d["ks"], d["preload"]) for d in rows.values() if "ks" in d and "preload" in d)


def plug_weight(port_in: float, fb: bool = False) -> float:
    """Table 4: average valve plug weight W (lb) for the smallest listed maximum port >= port_in."""
    best = None
    for r in c14("B-27.7", 2):
        if not r["column"].startswith("W ›") or ("FB" in r["column"]) != fb:
            continue
        lim = r["keys"]["Maximum Valve Port Diameter (in)"].replace("≤", "")
        if float(lim) >= port_in and (best is None or float(lim) < best[0]):
            best = (float(lim), _f(r["value"]))
    if best is None:
        raise ValueError(f"port {port_in} in is above table 4")
    return best[1]


def motl(size: str, model: str) -> float:
    """Table 5: manual override thrust limit (lb)."""
    for r in c14("B-27.7", 1):
        if r["keys"].get("Actuator Size") == size and model in r["column"]:
            return _f(re.sub(r"\(\d\)", "", r["value_raw"]))
    raise KeyError(size)


def tac(travel_in: float) -> float:
    """Tac = (valve travel + 0.25 in) rounded up to the nearest 0.50 in."""
    return math.ceil((travel_in + 0.25) / 0.5) * 0.5


def size_685s(model: str, *, a: float, b: float, c: float, d: float = 0.0, port_circumference_in: float,
              port_in: float, travel_in: float, supply_psig: float, pressure_tends_to: str, fb_valve: bool = False,
              tighter_than_class_iii: bool = False, manual_override: bool = False,
              sizes: list[str] | None = None) -> list[Check]:
    """685SE (spring extend) or 685SR (spring retract), steps 4 to 12 of pages B-27.1 to B-27.4.

    For each actuator size (smallest first) the lightest spring meeting the required spring thrust and the
    5 psi bench set is chosen, then thrust down/up, minimum supply, seat load and manual override are checked.
    """
    model = model.upper()
    pto = pressure_tends_to == "open"
    w = plug_weight(port_in, fb_valve)
    out = []
    for size, ar in sorted(table_685s().items(), key=lambda kv: int(kv[0])):
        if sizes and size not in sizes:
            continue
        pa, pra = ar["piston_in2"], ar["rod_in2"]
        t = tac(travel_in)
        if model == "685SE":
            shutoff = b if tighter_than_class_iii else min(40 * port_circumference_in, b)
            required = (a if pto else max(a, 0)) + shutoff + c + d + PF_PSI * pa
        else:
            sf = pa * 3
            required = (0 if pto else -min(a, 0)) + c + d + PF_PSI * pa + w + sf
        spring = next(((ks, pl) for ks, pl in springs_685s() if pl >= required and ks * t / (pa - pra) >= 5), None)
        if spring is None:
            out.append(Check(model, size, False, {"spring_available": False}, {"required_spring_thrust_lb": required},
                             "Fisher Catalog 14, page B-27.6 table 3"))
            continue
        ks, pl = spring
        if model == "685SE":
            down = supply_psig * pa + pl - PF_PSI * pa
            up = supply_psig * (pa - pra) - pl * 1.10 - 1.05 * ks * t - PF_PSI * pa
            valve_down, valve_up = a + b + c + d, c + d + w
            pre = (valve_down - pl) / pa + PF_PSI + 3
            prr = (valve_up + pl * 1.10 + ks * t * 1.05) / (pa - pra) + PF_PSI + 3
            stem = supply_psig * pa + pl * 1.10
            override = valve_up + pl * 1.10 + ks * t * 1.05 + PF_PSI * pa + 3 * pa
        else:
            down = supply_psig * pa - pl * 1.10 - 1.05 * ks * t - PF_PSI * pa
            up = supply_psig * pa + pl
            valve_down, valve_up = a + b + c + d, required - pa * 3
            pre = (valve_down + pl * 1.10 + ks * t * 1.05) / pa + PF_PSI + 3
            prr = (required - pl) / (pa - pra) + PF_PSI + 3
            stem = supply_psig * pa - pl - ks * t * 1.05
            override = valve_down + pl * 1.10 + ks * t * 1.05 + PF_PSI * pa + 3 * pa
        ps = max(pre, prr, 40.0)
        chk = {"thrust_down": down > valve_down, "thrust_up": up > valve_up, "min_supply_le_available": ps <= supply_psig,
               "supply_le_150": supply_psig <= MAX_CYLINDER_PSIG_685S,
               "seat_load_lt_1000_lb_per_in": down / port_circumference_in < 1000}
        if manual_override:
            chk["manual_override_le_motl"] = override <= motl(size, model)
        out.append(Check(model, size, all(chk.values()), chk,
                         {"required_spring_thrust_lb": required, "ks_lb_in": ks, "preload_lb": pl, "tac_in": t,
                          "bench_set_psi": ks * t / (pa - pra), "actuator_thrust_down_lb": down,
                          "actuator_thrust_up_lb": up, "valve_thrust_down_lb": valve_down, "valve_thrust_up_lb": valve_up,
                          "min_supply_psig": ps, "stem_load_lb": stem, "manual_override_thrust_lb": override,
                          "plug_weight_lb": w, "piston_in2": pa, "rod_in2": pra},
                         "Fisher Catalog 14, pages B-27.1 to B-27.7"))
    return out


# ------------------------------------------------------------------ 785C double-acting springless (B-27.8)

def table_785c() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in c14("B-27.8", 1):
        d = out.setdefault(r["keys"]["CYLINDER SIZE"], {})
        if r["column"] == "psig":
            d["max_cylinder_psig"] = _f(r["value"])
        elif "WITHOUT MANUAL OVERRIDE › lb" in r["column"]:
            d["max_thrust_lb"] = _f(r["value"])
        elif r["column"].endswith("› lb"):
            d["max_thrust_override_lb"] = _f(r["value"])
    for r in c14("B-27.8", 2):
        d = out.setdefault(r["keys"]["CYLINDER SIZE"], {})
        if r["column"].endswith("WITHOUT MANUAL OVERRIDE › Inches2"):
            d["piston_in2"] = _f(r["value"])
        elif r["column"].endswith("WITH MANUAL OVERRIDE(1) › Inches2"):
            d["piston_override_in2"] = _f(r["value"])
    return out


def select_785c(required_lb: float, supply_psig: float, *, manual_override: bool = False) -> list[Check]:
    """785C springless: force available = supply x piston area (table 2), within the maximum cylinder pressure
    and the maximum allowable thrust (table 1)."""
    out = []
    for size, r in sorted(table_785c().items(), key=lambda kv: int(kv[0])):
        area = r["piston_override_in2" if manual_override else "piston_in2"]
        avail = supply_psig * area
        limit = r["max_thrust_override_lb" if manual_override else "max_thrust_lb"]
        chk = {"force_available_ge_required": avail >= required_lb,
               "supply_le_max_cylinder_pressure": supply_psig <= r["max_cylinder_psig"],
               "force_le_max_thrust": avail <= limit}
        out.append(Check("785C", size, all(chk.values()), chk, {"force_available_lb": avail, "piston_in2": area,
                                                                  "max_thrust_lb": limit},
                         "Fisher Catalog 14, page B-27.8 tables 1 and 2"))
    return out


# ------------------------------------------------------------------ 3025 (B-73 to B-76)

@lru_cache(maxsize=1)
def table_3025() -> list[dict]:
    with open(C14.parent / "force" / "actuator_3025.csv", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def select_3025(required_lb: float, travel_in: float, *, action: str = "air-to-open",
                supply_bar: float | None = None, yoke_boss: str | None = None) -> list[dict]:
    """3025 'Available Actuator Force' (pages B-73 to B-76): rows at this travel whose thrust meets the
    required force. Air-to-open: spring thrust. Air-to-close: thrust at the printed supply (bar) not above
    supply_bar."""
    hits = []
    for r in table_3025():
        if r["action"] != action or abs(float(r["travel_in"]) - travel_in) > 0.01:
            continue
        if yoke_boss and yoke_boss not in r["yoke_boss"]:
            continue
        if action == "air-to-close" and supply_bar is not None and float(r["supply_bar"]) > supply_bar + 1e-9:
            continue
        if float(r["thrust_lb"]) >= required_lb:
            hits.append({**r, "thrust_lb": float(r["thrust_lb"]), "source": f"Fisher Catalog 14, page {r['printed_label']}"})
    return sorted(hits, key=lambda r: (r["size"], r["thrust_lb"]))
