"""Catalog 14 force method: match the valve body force (fisher.force) to an actuator.

Implemented:
  585C piston actuator, springless (Table 8, page B-24): force available scales with supply pressure.
  657, 657R, 667 spring-and-diaphragm actuators:
    - table method: the "Available Actuator Force" pages (B-31 to B-72) by size, supply range, travel, spring
    - calculated method (sample calculation B-81): ideal spring rate from force available and required

Not yet: 585C spring-biased, 685/685SE/685SR, 785C, 3025, 657C, stem load calculation (see docs/GAPS.md).
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from functools import lru_cache

from .force import FORCE_DIR

# Table 8, page B-24: 585C force available with 100 psig supply, maximum cylinder pressure, maximum thrust.
TABLE_8_585C = {  # size: (force_lb_at_100psig, max_cylinder_psig, max_thrust_lb)
    25: (2600, 150, 3900), 50: (4600, 150, 6900), 60: (5550, 150, 8300), 68: (8850, 140, 12500),
    80: (8850, 150, 13200), 100: (13050, 150, 19500), 130: (22150, 112, 25000),
}
# Table 10, page B-25: 585C yoke boss and valve stem diameters (inches) per size.
TABLE_10_585C = {
    25: [("2-1/8", 0.375), ("2-13/16", 0.5)], 50: [("2-13/16", 0.5), ("3-9/16", 0.75)], 60: [("3-9/16", 0.75)],
    68: [("3-9/16", 0.75)], 80: [("5", 1.0), ("5", 1.25)], 100: [("5", 1.0), ("5", 1.25)], 130: [("5", 1.25)],
}
# Table 13, page B-28: effective diaphragm area (square inches) for 657, 657C, 657R, 667.
DIAPHRAGM_AREA = {"30": 46, "34": 69, "40": 69, "45": 105, "46": 156, "50": 105, "60": 156, "70": 220,
                  "87": 220, "100": 450}
# Table 13: yoke boss diameter (inches) and valve stem connection per 657/667 size.
DIAPHRAGM_YOKE = {"30": ("2-1/8", 0.375), "34": ("2-1/8", 0.375), "40": ("2-13/16", 0.5), "45": ("2-13/16", 0.5),
                  "46": ("2-13/16", 0.5), "50": ("3-9/16", 0.75), "60": ("3-9/16", 0.75), "70": ("3-9/16", 0.75),
                  "87": ("5", 1.0), "100": ("5", 1.0)}


@dataclass
class ActuatorOption:
    actuator: str
    size: str
    force_available_lb: float
    passes: bool
    checks: dict = field(default_factory=dict)
    source: str = ""


def select_585c(required_lb: float, supply_psig: float, *, opening_required_lb: float | None = None,
                yoke_boss: str | None = None, stem_in: float | None = None) -> list[ActuatorOption]:
    """585C springless (page B-24): force available = Table 8 force x supply / 100 psig.

    Every size is returned in order with its checks; the first with passes=True is the selection.
    For pressure-tends-to-close valves, pass the opening force too (page B-3: the 585C uses both).
    """
    out = []
    for size, (f100, max_p, max_thrust) in TABLE_8_585C.items():
        fits = TABLE_10_585C[size]
        if yoke_boss and not any(y == yoke_boss for y, _ in fits):
            continue
        if stem_in and not any(abs(s - stem_in) < 1e-6 for _, s in fits):
            continue
        avail = f100 * supply_psig / 100
        checks = {"force_available_ge_required": avail >= required_lb,
                  "supply_le_max_cylinder_pressure": supply_psig <= max_p,
                  "force_le_max_thrust": avail <= max_thrust}
        if opening_required_lb is not None:
            checks["force_available_ge_opening"] = avail >= opening_required_lb
        out.append(ActuatorOption("585C", str(size), avail, all(checks.values()),
                                  {**checks, "max_cylinder_psig": max_p, "max_thrust_lb": max_thrust},
                                  "Catalog 14 tables 8 and 10, pages B-24/B-25"))
    return out


@lru_cache(maxsize=1)
def diaphragm_table() -> list[dict]:
    with open(FORCE_DIR / "diaphragm_force.csv", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _size_key(size: str) -> str:
    return re.match(r"\d+", size).group()


def select_diaphragm(required_lb: float, travel_in: float, *, actuator: str = "657", supply: str = "0-18",
                     yoke_boss: str | None = None) -> list[dict]:
    """Table method (pages B-31 to B-72): springs whose available force at this travel is at least the
    required force, smallest actuator first, then the largest margin of bench set flexibility."""
    hits = []
    for r in diaphragm_table():
        if r["actuator"] != actuator or r["supply"] != supply or abs(float(r["travel_in"]) - travel_in) > 1e-6:
            continue
        if yoke_boss and DIAPHRAGM_YOKE.get(_size_key(r["size"]), ("",))[0] != yoke_boss:
            continue
        if float(r["force_lb"]) >= required_lb:
            hits.append({**r, "force_lb": float(r["force_lb"]),
                         "source": f"Fisher Catalog 14, page {r['printed_label']}"})
    return sorted(hits, key=lambda r: (int(_size_key(r["size"])), r["force_lb"]))


def spring_rate_calc(required_lb: float, travel_in: float, area_in2: float, *, max_pressure_psig: float = 15,
                     initial_pressure_psig: float = 3) -> dict:
    """Calculated method (sample calculation, page B-81): the ideal spring compression rate.

    force available = max pressure x area; initial force = initial pressure x area;
    net force = available - initial - required; ideal rate = net / travel.
    Choose the listed spring with the largest rate not greater than the ideal rate.
    """
    available = max_pressure_psig * area_in2
    initial = initial_pressure_psig * area_in2
    net = available - initial - required_lb
    return {"force_available_lb": available, "initial_force_lb": initial, "net_force_lb": net,
            "ideal_spring_rate_lb_in": net / travel_in if travel_in else None,
            "feasible": net > 0}


def springs_for_rate(actuator: str, size: str, ideal_rate: float) -> list[dict]:
    """Springs listed for an actuator size with a rate at or below `ideal_rate`, stiffest first."""
    seen, out = set(), []
    for r in diaphragm_table():
        if r["actuator"] == actuator and _size_key(r["size"]) == _size_key(size) and r["spring"] not in seen:
            seen.add(r["spring"])
            rate = float(r["spring_rate_lb_in"])
            if rate <= ideal_rate:
                out.append({"spring": r["spring"], "spring_rate_lb_in": rate, "printed_label": r["printed_label"]})
    return sorted(out, key=lambda r: -r["spring_rate_lb_in"])
