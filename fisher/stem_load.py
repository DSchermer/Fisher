"""Catalog 14 stem load calculations (pages B-99 to B-105): the actuator force must not exceed the maximum
allowable valve stem load.

  1. Table 1 (usage guide) gives, per valve design / size / rating / bonnet / stem, which pair of tables
     applies: 3 & 4 (L/D up to 12.5), 5 & 6 (up to 15), 7 & 8 (up to 20), or a per-valve table (2, 9).
  2. Strain-hardened 316 stems: read the load from table 3, 5 or 7 (interpolate in temperature).
  3. Other stem materials: reference load (table 4, 6 or 8 header) x material factor at temperature.
  4. Minimum material factor for an actuator force: force / reference load.

Packing friction is excluded from the required closing force but must be included in the available actuator
force compared with the stem load (page B-99).
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache

from .force import FORCE_DIR


@lru_cache(maxsize=None)
def _rows(name: str) -> list[dict]:
    with open(FORCE_DIR / f"{name}.csv", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def usage_guide() -> list[dict]:
    return _rows("usage_guide")


def tables_for(design: str, *, nps: str | None = None, rating: str | None = None, bonnet: str | None = None,
               stem_in: float | None = None) -> list[dict]:
    """Table 1 rows that name this valve design (e.g. 'ED'), narrowed by the other fields where given."""
    out = []
    for r in usage_guide():
        names = [n.strip() for n in re.split(r",|&|\band\b", re.sub(r"\(\d+\)", "", r["design"])) if n.strip()]
        if design.upper() not in [n.upper() for n in names]:
            continue
        if nps and r["nps"] not in ("- - -", "") and not re.match(re.escape(str(nps)) + r"(\(|$| )", r["nps"]):
            continue
        if bonnet and bonnet.lower() not in r["bonnet"].lower():
            continue
        if rating and r["rating"] not in ("- - -", "") and rating.replace("CL", "") not in r["rating"]:
            continue
        if stem_in is not None and r["stem_in"] not in ("- - -", ""):
            listed = [float(x) for x in re.findall(r"\d+\.\d+|\d+", r["stem_in"].replace("1 1/4", "1.25")
                                                    .replace("1/2", "0.5").replace("3/4", "0.75"))]
            if listed and not any(abs(stem_in - x) < 1e-6 for x in listed):
                continue
        out.append(r)
    return out


def _interp(points: list[tuple[float, float]], x: float) -> float | None:
    points = sorted(points)
    if not points or x > points[-1][0]:
        return None
    if x <= points[0][0]:
        return points[0][1]  # "to 100 F": the first column covers all lower temperatures
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return None


@dataclass
class StemLoad:
    max_stem_load_lb: float | None
    basis: str
    source: str


def max_stem_load(stem_in: float, temp_f: float, *, table: int = 3, material: str | None = None) -> StemLoad:
    """Maximum allowable stem load (lb). table: 3, 5 or 7 for the L/D group (from tables_for()).
    material None = strain-hardened 316; otherwise a name or part of one from the material-factor table."""
    if table not in (3, 5, 7):
        raise ValueError("table must be 3, 5 or 7; tables 2 and 9 are per-valve (valve_stem_loads())")
    if material is None or re.search(r"strain.hardened", material, re.I):
        pts = [(float(r["temp"]), float(r["load"])) for r in _rows("stem_load_316")
               if r["table"] == str(table) and r["unit_system"] == "F" and abs(float(r["stem_in"]) - stem_in) < 1e-6]
        v = _interp(pts, temp_f)
        return StemLoad(v, f"table {table}, strain-hardened 316, interpolated in temperature",
                        f"Fisher Catalog 14, page {_label(table)}")
    ftable = table + 1
    ref = next((float(r["reference_lb"]) for r in _rows("stem_reference")
                if r["table"] == str(ftable) and abs(float(r["stem_in"]) - stem_in) < 1e-6), None)
    names = sorted({r["material"] for r in _rows("stem_material") if r["table"] == str(ftable)
                    and material.lower() in r["material"].lower()})
    if len(names) != 1:
        raise KeyError(f"material '{material}' matches {names or 'nothing'} in table {ftable}")
    pts = [(float(r["temp_f"]), float(r["factor"])) for r in _rows("stem_material")
           if r["table"] == str(ftable) and r["material"] == names[0]]
    f = _interp(pts, temp_f)
    if ref is None or f is None:
        return StemLoad(None, f"no reference load or factor for {stem_in} in at {temp_f:g} F", "")
    return StemLoad(ref * f, f"table {ftable}: reference {ref:g} lb x factor {f:.3f} ({names[0]})",
                    f"Fisher Catalog 14, page {_label(ftable)}")


def minimum_material_factor(actuator_force_lb: float, stem_in: float, *, table: int = 4) -> float | None:
    """Page B-99: available actuator force / reference load of the stem diameter."""
    ref = next((float(r["reference_lb"]) for r in _rows("stem_reference")
                if r["table"] == str(table) and abs(float(r["stem_in"]) - stem_in) < 1e-6), None)
    return actuator_force_lb / ref if ref else None


def valve_stem_loads(valve: str | None = None) -> list[dict]:
    """Tables 2 and 9: per-valve maximum stem loads (ET-C, EWT-C, EZ-C; HPT-C, HPS-C)."""
    return [r for r in _rows("stem_load_valve") if not valve or valve.upper() in r["valve"].upper()]


def check(actuator_force_lb: float, stem_in: float, temp_f: float, *, table: int = 3,
          material: str | None = None) -> dict:
    s = max_stem_load(stem_in, temp_f, table=table, material=material)
    ok = None if s.max_stem_load_lb is None else actuator_force_lb <= s.max_stem_load_lb
    return {"actuator_force_lb": actuator_force_lb, "max_stem_load_lb": s.max_stem_load_lb, "within_limit": ok,
            "basis": s.basis, "source": s.source}


def _label(table: int) -> str:
    return {3: "B-102", 4: "B-102", 5: "B-103", 6: "B-103", 7: "B-104", 8: "B-104"}[table]
