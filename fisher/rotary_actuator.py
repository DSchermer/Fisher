"""Catalog 14 torque method, actuator side: rotary actuator torque output (1051, 1052, 1061, 1068, 2052)
and selection against a valve's breakout and dynamic torque (fisher.torque).

Data: data/catalog14/torque/actuator_torque.csv (extract/catalog14_actuator_torque.py), one row per printed
value, with actuator, the valves the page says it is used with, flow, size, diaphragm range or supply,
spring, initial compression, action and what the value is (TB, TD at an angle, ...).

Selection (page D-3 step 3: "Be sure the actuator capability exceeds the required valve torque"):
  breakout: actuator TB (or unseating / breakout torque) >= valve TB
  dynamic:  at every angle where the valve's TD is known, the actuator's torque at that angle >= valve TD.
            Where the actuator table prints fewer angles, the smallest printed dynamic torque is used and noted.
  1061: torque = (torque per psig at the angle) x cylinder pressure, which must not exceed the size's maximum.
  1068 double acting: torque at the supply pressure (the same at every angle).
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from functools import lru_cache

from .torque import TORQUE_DIR


@lru_cache(maxsize=1)
def actuator_torque() -> list[dict]:
    with open(TORQUE_DIR / "actuator_torque.csv", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _valve_tokens(valve: str) -> list[str]:
    return [t for t in re.split(r"[/,\s]+", valve.replace("NPS 14-36", "")) if t and not t.startswith("CL")]


def used_with(row: dict, valve: str | None) -> bool:
    if not valve:
        return True
    text = row["used_with"].lower()
    if text == "all valves":
        return True
    return any(re.search(r"(?<![\w-])" + re.escape(t.lower()) + r"(?![\w])", text) for t in _valve_tokens(valve))


@dataclass
class ActuatorChoice:
    actuator: str
    size: str
    action: str
    diaphragm_psig: str
    supply: str
    spring: str
    initial_compression_psig: str
    used_with: str
    flow: str
    breakout_available: float | None
    dynamic_available: dict  # angle -> lbf-in
    passes: bool | None
    checks: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    source: str = ""


def configurations(*, actuator: str | None = None, valve: str | None = None, action: str | None = None,
                   flow: str | None = None, attenuator: bool | None = None) -> list[dict]:
    """Group the printed values into actuator configurations (one table row and action)."""
    groups: dict[tuple, dict] = {}
    for r in actuator_torque():
        if actuator and r["actuator"] != actuator:
            continue
        if not used_with(r, valve):
            continue
        if action and r["action"] and action.lower() != r["action"].lower():
            continue
        if flow and r["flow"] and flow.lower() != r["flow"]:
            continue
        if attenuator is not None and ("attenuator" in r["used_with"].lower()) != attenuator:
            continue
        key = (r["page"], r["table_no"], r["row_no"], r["action"])
        g = groups.setdefault(key, {"row": r, "values": []})
        g["values"].append(r)
    return list(groups.values())


def _available(values: list[dict], supply_psig: float | None) -> tuple[float | None, dict, list]:
    notes = []
    by_q: dict[str, list] = {}
    for v in values:
        by_q.setdefault(v["quantity"], []).append(v)
    breakout = None
    for q in ("TB", "TB_UNSEATING", "UNSEATING", "BREAKOUT"):
        if q in by_q:
            breakout = float(by_q[q][0]["value"])
            if q != "TB":
                notes.append(f"breakout from {q.lower()} torque")
            break
    dyn = {}
    for q in ("TD", "TORQUE"):
        for v in by_q.get(q, []):
            if v["angle_deg"] != "":
                dyn[float(v["angle_deg"])] = float(v["value"])
    for v in by_q.get("TD_MAX_ROTATION", []):
        dyn.setdefault(float(v["max_rotation_deg"]), float(v["value"]))
    if breakout is None and 0.0 in dyn:
        breakout = dyn[0.0]
        notes.append("breakout from the torque at 0 deg (closed)")
    if "TORQUE_AT_SUPPLY" in by_q:
        at = {float(re.match(r"[\d.]+", v["supply"]).group()): float(v["value"]) for v in by_q["TORQUE_AT_SUPPLY"]
              if v["unit"] == "lbf-in"}
        if supply_psig is not None and at:
            usable = [p for p in at if p <= supply_psig]
            if usable:
                t = at[max(usable)]
                breakout = t
                dyn = {a: t for a in range(0, 100, 10)}
                notes.append(f"double acting: torque at {max(usable):g} psig supply (not above {supply_psig:g})")
            else:
                notes.append(f"no printed supply at or below {supply_psig:g} psig")
    if "PER_PSIG" in by_q:
        if supply_psig is None:
            notes.append("1061: pass supply_psig (cylinder pressure) to get torque")
        else:
            limit = float(by_q["MAX_CYLINDER_PSIG"][0]["value"]) if "MAX_CYLINDER_PSIG" in by_q else None
            p = min(supply_psig, limit) if limit else supply_psig
            if limit and supply_psig > limit:
                notes.append(f"cylinder pressure limited to the maximum {limit:g} psig")
            for v in by_q["PER_PSIG"]:
                m = re.search(r"(\d+) or (\d+)", v["column_path"])
                if m:
                    t = float(v["value"]) * p
                    dyn[float(m.group(1))] = dyn[float(m.group(2))] = t
            breakout = dyn.get(0.0)
    return breakout, dyn, notes


def select(required_breakout: float | None, required_dynamic: dict | None = None, *, valve: str | None = None,
           actuator: str | None = None, action: str | None = None, flow: str | None = None,
           attenuator: bool | None = None, diaphragm_psig: str | None = None,
           supply_psig: float | None = None) -> list[ActuatorChoice]:
    """Every actuator configuration printed for this valve, with whether it covers the valve torque.

    required_dynamic: angle -> valve dynamic torque (lbf-in), e.g. RotaryTorque.dynamic_lbf_in.
    Results: passing configurations first, smallest actuator size first.
    """
    out = []
    for g in configurations(actuator=actuator, valve=valve, action=action, flow=flow, attenuator=attenuator):
        r = g["row"]
        if diaphragm_psig and r["diaphragm_psig"] and r["diaphragm_psig"] != diaphragm_psig:
            continue
        breakout, dyn, notes = _available(g["values"], supply_psig)
        checks = {}
        if required_breakout is not None:
            checks["breakout"] = None if breakout is None else breakout >= required_breakout
        for ang, need in sorted((required_dynamic or {}).items()):
            ang = float(ang)
            have = dyn.get(ang)
            if have is None and dyn:
                have = min(dyn.values())
                notes.append(f"no actuator torque printed at {ang:g} deg; smallest printed dynamic torque used")
            checks[f"dynamic_{ang:g}"] = None if have is None else have >= need
        known = [v for v in checks.values() if v is not None]
        passes = (all(known) if known else None) if None not in checks.values() else (False if False in known else None)
        out.append(ActuatorChoice(r["actuator"], r["size"], r["action"], r["diaphragm_psig"], r["supply"], r["spring"],
                                  r["initial_compression_psig"], r["used_with"], r["flow"], breakout, dyn, passes,
                                  checks, sorted(set(notes)), f"Fisher Catalog 14, page {r['printed_label']}"))

    def size_num(c):
        m = re.match(r"\d+", c.size or "")
        return int(m.group()) if m else 9999
    return sorted(out, key=lambda c: (c.passes is not True, size_num(c)))
