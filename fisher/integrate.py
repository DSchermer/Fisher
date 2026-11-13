"""Link Catalog 12 valve configurations (config ids) to Catalog 14 actuator ratings.

Sliding-stem valves (Catalog 14 section A): matched on port diameter and travel, which Catalog 12 prints
for each configuration, and on balanced/unbalanced construction. Catalog 14 page A-2 lists the valves
its pressure drop tables cover:
    Balanced:    ED and EWD (Class II), ET and EWT (Class IV metal seats, Class V PTFE seats)
    Unbalanced:  D, ES and EWS, EZ (Class IV)
Rows Catalog 14 marks for one valve, e.g. "(ET, Class V Leakage)", only match that valve.

Rotary valves (Catalog 14 section C): matched on valve family and NPS.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import actuators
from .catalog import Catalog, Config

# Catalog 14 page A-2: valve -> (construction, default leakage class)
SLIDING_COVERAGE = {
    "ED": ("Balanced", "Class II"), "EWD": ("Balanced", "Class II"),
    "ET": ("Balanced", "Class IV"), "EWT": ("Balanced", "Class IV"),
    "D": ("Unbalanced", "Class IV"), "ES": ("Unbalanced", "Class IV"),
    "EWS": ("Unbalanced", "Class IV"), "EZ": ("Unbalanced", "Class IV"),
}
ROTARY_TOKEN = re.compile(r"Control-Disk|[A-Z]{0,2}\d{2,5}[A-Z]?")


@dataclass
class ActuatorMatch:
    config_id: str
    method: str                       # "sliding-stem" | "rotary" | ""
    matched_on: dict = field(default_factory=dict)
    ratings: list = field(default_factory=list)
    note: str = ""

    def to_dict(self, limit: int | None = None) -> dict:
        rs = self.ratings[:limit] if limit else self.ratings
        return {"config_id": self.config_id, "method": self.method, "matched_on": self.matched_on,
                "count": len(self.ratings), "ratings": [r.to_dict() for r in rs], "note": self.note}


def _inches(config: Config, word: str) -> float | None:
    """A dimension printed in inches, e.g. port diameter "1/4" -> 0.25, "3.4375" -> 3.4375."""
    for k, v in config.attrs.items():
        if re.search(word, k, re.I) and re.search(r"inch", k, re.I):
            size = actuators._size(v)
            if size is not None:
                return size
    return None


def sliding_valve_codes(config: Config) -> list[str]:
    """Which Catalog 14 section A valves a Catalog 12 configuration is (ED, ET, ES, EZ, D, EWD, EWS, EWT).
    EW pages can name several ("EWT-2, EWD, and EWT"); all are returned, in the order printed."""
    if config.family == "EW":
        return list(dict.fromkeys(c for c in re.findall(r"\bEW[DST]\b", config.page_title) if c in SLIDING_COVERAGE))
    return [config.family] if config.family in SLIDING_COVERAGE else []


def sliding_valve_code(config: Config) -> str | None:
    codes = sliding_valve_codes(config)
    return codes[0] if codes else None


def rotary_tokens(text: str) -> set[str]:
    return set(ROTARY_TOKEN.findall(text.replace("™", "")))


def actuators_for_config(config: Config, dp_required: float = 0.0, *, angle_deg: float | None = None,
                         leakage: str | None = None, valve_code: str | None = None) -> ActuatorMatch:
    """Catalog 14 constructions rated for this Catalog 12 configuration at `dp_required` psi or more."""
    if config.position_basis == "deg_rotation":
        tokens = {config.family.replace("™", "")}
        hits = [r for r in actuators.ratings() if r.section == "C" and r.unit == "psi"
                and tokens & rotary_tokens(r.valve) and r.valve_nps in config.sizes
                and r.value >= dp_required and (angle_deg is None or r.angle_deg == angle_deg)]
        hits.sort(key=lambda r: (r.actuator, r.page, r.angle_deg or 0, r.column))
        m = ActuatorMatch(config.config_id, "rotary", {"valve": config.family, "nps": config.sizes,
                                                       "angle_deg": angle_deg}, hits)
        if not hits:
            m.note = (f"Catalog 14 section C has no pressure drop table for {config.family} NPS "
                      f"{config.nps}" + (f" at {angle_deg:g} degrees" if angle_deg is not None else "") +
                      "; see the torque method (section D).")
        return m

    codes = sliding_valve_codes(config)
    code = valve_code or (codes[0] if codes else None)
    port, travel = _inches(config, "port"), _inches(config, "travel")
    m = ActuatorMatch(config.config_id, "sliding-stem",
                      {"valve": code, "port_in": port, "travel_in": travel})
    if len(codes) > 1 and not valve_code:
        m.matched_on["also_applies_to"] = codes[1:]
    if code not in SLIDING_COVERAGE:
        m.note = (f"Catalog 14's pressure drop tables cover D, ED, ES, ET, EZ, EWD, EWS and EWT; "
                  f"for {config.family} use the force method (section B).")
        return m
    if port is None or travel is None:
        m.note = "This configuration does not list a port diameter and travel in inches."
        return m
    balance, default_leak = SLIDING_COVERAGE[code]
    leak = leakage or None
    m.matched_on.update({"balance": balance, "leakage": leak or f"any (catalog default {default_leak})"})
    candidates = [r for r in actuators.ratings() if r.section == "A" and r.unit == "psi"
                  and r.port_in is not None and abs(r.port_in - port) < 0.002 and r.balance == balance
                  and (leak is None or r.leakage == leak)]
    # Rows marked for one valve, e.g. "(ET, Class V Leakage)", only apply to that valve.
    def for_this_valve(r) -> bool:
        named = re.findall(r"\(([A-Z]{1,3}),", r.group)
        return not named or named[0] == code or (named[0] == "ED" and code == "EWD") or (named[0] == "ET" and code == "EWT")
    candidates = [r for r in candidates if for_this_valve(r)]
    hits = [r for r in candidates if r.travel_in is not None and abs(r.travel_in - travel) < 0.002 and r.value >= dp_required]
    if not hits and candidates:
        travels = sorted({r.travel_in for r in candidates if r.travel_in})
        m.note = (f"Catalog 14 lists the {port:g} inch port at travel {', '.join(f'{t:g}' for t in travels)} inch, "
                  f"not {travel:g}." if not any(abs(t - travel) < 0.002 for t in travels) else
                  f"No construction reaches {dp_required:g} psi for this port and travel.")
    elif not candidates:
        m.note = f"Catalog 14 has no {balance.lower()} pressure drop table for a {port:g} inch port."
    hits.sort(key=lambda r: (r.actuator, actuators._actuator_number(r.actuator_size), r.page, r.value))
    m.ratings = hits
    return m


def coverage(cat: Catalog | None = None) -> dict:
    """How many Catalog 12 configurations link to at least one Catalog 14 rating."""
    cat = cat or Catalog.load()
    out = {"sliding-stem": [0, 0], "rotary": [0, 0]}
    for c in cat.configs.values():
        if c.family == "Fd Style Modifiers" or not c.curves:
            continue
        m = actuators_for_config(c)
        if not m.method:
            continue
        out[m.method][1] += 1
        out[m.method][0] += bool(m.ratings)
    return {k: {"linked": v[0], "configs": v[1]} for k, v in out.items()}
