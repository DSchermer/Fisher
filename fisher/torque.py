"""Catalog 14 torque method for rotary valves (section D, page D-3 onward).

    Breakout torque   TB = A (dP_shutoff) + B
    Dynamic torque    TD = C (dP_eff)
    dP_eff: the smaller of the actual flowing pressure drop at the maximum angle of rotation and the
            effective pressure drop from the valve's Table 2 (e.g. 0.600 x P1 abs for liquids at 60 deg)
    Both must be below the shaft's maximum allowable torque, scaled by the shaft material's relative
    strength at temperature (Table 3).

Torques in lbf-in, pressures psi (P1 in psig; absolute adds 14.7).

Typed valve data so far: the 7600 butterfly (pages D-4 to D-6). For other valves the A, B, C factors
and limits are in the Catalog 14 tables kept as printed (fisher.actuators.search_tables), and can be
passed to these functions directly.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ATM_PSI = 14.7


def breakout_torque(a: float, b: float, dp_shutoff: float) -> float:
    """TB = A (dP_shutoff) + B, lbf-in."""
    return a * dp_shutoff + b


def effective_dp(p1_psig: float, factor: float, actual_dp: float | None = None) -> tuple[float, str]:
    """dP_eff = factor x P1 abs, or the actual flowing pressure drop if that is smaller (page D-4)."""
    calc = factor * (p1_psig + ATM_PSI)
    if actual_dp is not None and actual_dp <= calc:
        return actual_dp, f"actual dP {actual_dp:g} <= {factor:g} x P1abs = {calc:.3g}; actual used"
    return calc, f"{factor:g} x P1abs = {calc:.3g}"


def dynamic_torque(c: float, dp_eff: float) -> float:
    """TD = C (dP_eff), lbf-in."""
    return c * dp_eff


@dataclass
class TorqueResult:
    breakout_lbf_in: float
    dynamic_lbf_in: float
    dp_eff: float
    dp_eff_basis: str
    max_allowable_lbf_in: float | None
    within_shaft_limit: bool | None
    governing_lbf_in: float


def valve_torque(*, a: float, b: float, c: float, dp_shutoff: float, p1_psig: float, dp_eff_factor: float,
                 actual_dp: float | None = None, max_allowable_lbf_in: float | None = None,
                 relative_strength_pct: float = 100.0) -> TorqueResult:
    """Valve torque requirements and the shaft check (page D-4 procedure)."""
    tb = breakout_torque(a, b, dp_shutoff)
    dpe, basis = effective_dp(p1_psig, dp_eff_factor, actual_dp)
    td = dynamic_torque(c, dpe)
    limit = max_allowable_lbf_in * relative_strength_pct / 100 if max_allowable_lbf_in is not None else None
    ok = None if limit is None else (tb < limit and td < limit)
    return TorqueResult(tb, td, dpe, basis, limit, ok, max(tb, td))


# ------------------------------------------------------------------ 7600 butterfly, pages D-4 to D-6

TORQUE_DIR = Path(__file__).resolve().parent.parent / "data" / "catalog14" / "torque"
# Table 2, page D-6: effective pressure drop factors (x P1 abs) for the 7600 FISHTAIL disk
DP_EFF_7600 = {("liquid", 60): 0.600, ("liquid", 90): 0.450, ("gas", 60): 0.180, ("gas", 90): 0.090}


@lru_cache(maxsize=1)
def torque_characteristics() -> list[dict]:
    """Typed Table 1 torque characteristics (so far the 7600 butterfly, pages D-5/D-6)."""
    with open(TORQUE_DIR / "torque_characteristics.csv", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def lookup(valve: str, nps: int | str, bearing: str, shaft_in: str | None = None) -> list[dict]:
    return [r for r in torque_characteristics() if r["valve"] == valve and r["nps"] == str(nps)
            and bearing.lower() in r["bearing"].lower() and (shaft_in is None or r["shaft_in"] == shaft_in)]


# ------------------------------------------------------------------ every valve in section D

def effective_dp_liquid(p1_psig: float, fl: float, ff: float, pv_psia: float) -> float:
    """dP eff for liquids (page D-10): FL^2 (P1 abs - FF Pv)."""
    return fl * fl * (p1_psig + ATM_PSI - ff * pv_psia)


def effective_dp_gas(p1_psig: float, k: float) -> float:
    """dP eff for gas (page D-10): K x P1 abs."""
    return k * (p1_psig + ATM_PSI)


@lru_cache(maxsize=1)
def torque_factors() -> list[dict]:
    """Typed torque factors for every rotary valve in section D (extract/catalog14_torque_factors.py)."""
    with open(TORQUE_DIR / "torque_factors.csv", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def valves() -> list[str]:
    return sorted({r["valve"] for r in torque_factors()})


def _nps_match(printed: str, nps) -> bool:
    import re
    p = re.sub(r"\(\d\)", "", printed or "").replace("‐", "-").strip()
    q = str(nps).strip()
    if p == q:
        return True
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:-|–|through|to)\s*(\d+(?:\.\d+)?)", p)
    if m:  # a size range, e.g. K values for "14-24"
        try:
            return float(m.group(1)) <= _frac(q) <= float(m.group(2))
        except ValueError:
            return False
    try:
        return abs(_frac(p) - _frac(q)) < 1e-9
    except ValueError:
        return False


def _frac(x: str) -> float:
    x = x.replace("‐", "-").strip()
    if "-" in x and "/" in x:  # 1-1/2
        whole, f = x.split("-", 1)
        n, d = f.split("/")
        return int(whole) + int(n) / int(d)
    if " " in x and "/" in x:
        whole, f = x.split(" ", 1)
        n, d = f.split("/")
        return int(whole) + int(n) / int(d)
    if "/" in x:
        n, d = x.split("/")
        return int(n) / int(d)
    return float(x)


@dataclass
class TorqueOption:
    """One printed row of a valve's torque characteristics: a size, shaft and construction."""
    valve: str
    variant: str
    nps: str
    shaft: str
    construction: str
    flow: str
    pressure_class: str
    a: dict  # qualifier ('' or e.g. 'Up to 300 psi') -> A
    b: dict  # qualifier ('' or seal material) -> B, lbf-in
    c: dict  # angle (deg) -> C
    mast: dict  # qualifier ('' or shaft material / bearing) -> lbf-in
    direction: dict  # angle -> 'tends to open' / 'tends to close', where printed
    other: dict
    source: str


def options(valve: str, nps, *, flow: str | None = None, pressure_class: str | None = None,
            construction: str | None = None, variant: str | None = None) -> list[TorqueOption]:
    """Every printed torque-characteristics row for this valve and size (A/B/C/MAST grouped by row).

    Filters are case-insensitive substrings. C factors printed in a separate table from A and B (V150 with
    attenuator, V250, V260, V270, V280) come back as their own options; use `combined()` to join them.
    """
    groups: dict[tuple, list] = {}
    for r in torque_factors():
        if r["valve"].lower() != valve.lower() or not _nps_match(r["nps"], nps):
            continue
        if r["factor"] not in ("A", "B", "C", "MAST") and not r["factor"].startswith(("E", "F", "BREAK", "RUN")):
            continue
        if flow and flow.lower() not in r["flow"].lower() and r["flow"] != "forward and reverse":
            continue
        if pressure_class and pressure_class.lower() not in (r["pressure_class"] + " " + r["qualifier"]).lower():
            continue
        if construction and construction.lower() not in r["construction"].lower():
            continue
        if variant is not None and variant.lower() not in r["variant"].lower():
            continue
        groups.setdefault((r["page"], r["table_no"], r["row_no"]), []).append(r)
    out = []
    for rows in groups.values():
        r0 = rows[0]
        opt = TorqueOption(r0["valve"], r0["variant"], r0["nps"], r0["shaft"], r0["construction"], r0["flow"],
                           r0["pressure_class"], {}, {}, {}, {}, {}, {}, f"Fisher Catalog 14, page {r0['printed_label']}")
        for r in rows:
            v = float(r["value"])
            if r["factor"] == "A":
                opt.a[r["qualifier"]] = v
            elif r["factor"] == "B":
                opt.b[r["qualifier"]] = v
            elif r["factor"] == "C" and r["angle_deg"]:
                opt.c[float(r["angle_deg"])] = v
                if r["torque_direction"]:
                    opt.direction[float(r["angle_deg"])] = r["torque_direction"]
            elif r["factor"] == "MAST":
                opt.mast[r["qualifier"]] = v
            else:
                opt.other[f"{r['factor']} {r['qualifier']}".strip()] = v
        out.append(opt)
    return out


def combined(valve: str, nps, **filters) -> list[TorqueOption]:
    """options(), with C factors and MAST from a separate C-factor table merged into the A/B rows
    of the same valve, size and variant (layouts that print breakout and dynamic factors apart)."""
    opts = options(valve, nps, **filters)
    ab = [o for o in opts if o.a or o.b]
    cs = [o for o in opts if o.c and not (o.a or o.b)]
    for o in ab:
        if not o.c:
            match = [c for c in cs if c.variant == o.variant and (not o.shaft or not c.shaft or o.shaft == c.shaft)]
            if len(match) >= 1:
                o.c = dict(match[0].c)
                o.direction = dict(match[0].direction)
                o.mast = o.mast or dict(match[0].mast)
                o.source += f"; C from {match[0].source.split(', ')[-1]}"
    return ab or opts


def k_values(valve: str, nps, *, flow: str | None = None, pressure_class: str | None = None,
             variant: str | None = None) -> dict[str, dict[float, float]]:
    """K factors for effective pressure drop (gas: dP eff = K x P1 abs) by angle, one dict per printed
    table/qualifier (e.g. 'Forward Flow › Full Port')."""
    out: dict[str, dict[float, float]] = {}
    for r in torque_factors():
        if r["factor"] != "K" or r["valve"].lower() != valve.lower() or not _nps_match(r["nps"], nps):
            continue
        if flow and flow.lower() not in (r["flow"] + r["qualifier"]).lower() and r["flow"] != "forward and reverse":
            continue
        if pressure_class and pressure_class.lower() not in (r["pressure_class"] + r["construction"] + r["qualifier"]).lower():
            continue
        if variant is not None and variant.lower() not in r["variant"].lower():
            continue
        key = " | ".join(x for x in (r["pressure_class"], r["construction"], r["qualifier"],
                                     f"page {r['printed_label']} table {r['table_no']}") if x)
        out.setdefault(key, {})[float(r["angle_deg"])] = float(r["value"])
    return out


def shaft_strength(valve: str) -> list[dict]:
    """Relative shaft strength (percent of MAST) by material and temperature range, where printed."""
    return [{"material": next(iter(json.loads(r["other_keys"]).values())) if r["other_keys"] else r["construction"],
             "temperature_f": r["qualifier"],
             "percent": float(r["value"]), "source": f"Fisher Catalog 14, page {r['printed_label']}"}
            for r in torque_factors() if r["factor"] == "STRENGTH" and r["valve"].lower() == valve.lower()]


@dataclass
class RotaryTorque:
    option: TorqueOption
    breakout_lbf_in: float | None
    dynamic_lbf_in: dict  # angle -> TD
    dp_eff: dict  # angle -> (dp used, basis)
    mast_lbf_in: float | None
    within_mast: bool | None
    governing_lbf_in: float | None
    notes: list


def valve_torque_catalog(valve: str, nps, *, dp_shutoff: float, p1_psig: float, angles=None,
                         fluid: str = "liquid", fl: float | None = None, ff: float | None = None,
                         pv_psia: float | None = None, k: dict | None = None, actual_dp: dict | None = None,
                         a_key: str | None = None, b_key: str | None = None, mast_key: str | None = None,
                         relative_strength_pct: float = 100.0, **filters) -> list[RotaryTorque]:
    """Breakout and dynamic torque for every matching printed row (page D-10 procedure).

    dP eff at each angle: liquid FL^2 (P1abs - FF Pv); gas K x P1abs (K from `k`, or the valve's K table
    when exactly one applies); the actual flowing dP at that angle is used instead when it is smaller.
    Where a row prints several B values (seal materials) or MASTs (shaft materials), pass b_key/mast_key;
    otherwise the largest B and the smallest MAST are used (conservative) and noted.
    """
    out = []
    for o in combined(valve, nps, **filters):
        notes = []

        def pick(d: dict, key: str | None, largest: bool, what: str):
            if not d:
                return None
            if key is not None:
                hit = [v for q, v in d.items() if key.lower() in q.lower()]
                if hit:
                    return hit[0]
                notes.append(f"{what} '{key}' not printed for this row; options: {sorted(d)}")
            v = max(d.values()) if largest else min(d.values())
            if len(d) > 1:
                notes.append(f"{what}: {'largest' if largest else 'smallest'} of {d} used")
            return v

        a = pick(o.a, a_key, True, "A")
        b = pick(o.b, b_key, True, "B")
        tb = breakout_torque(a, b, dp_shutoff) if a is not None and b is not None else None
        kk = k
        if fluid == "gas" and kk is None:
            tables = k_values(valve, nps, flow=filters.get("flow"), pressure_class=filters.get("pressure_class"))
            if len(tables) == 1:
                kk = next(iter(tables.values()))
            elif tables:
                notes.append(f"several K tables apply, pass k=: {sorted(tables)}")
        td, dpe = {}, {}
        for ang in sorted(angles or o.c):
            cval = o.c.get(float(ang))
            if cval is None:
                continue
            if fluid == "liquid":
                if None in (fl, ff, pv_psia):
                    notes.append("liquid dP eff needs fl, ff and pv_psia")
                    break
                calc, basis = effective_dp_liquid(p1_psig, fl, ff, pv_psia), "FL^2 (P1abs - FF Pv)"
            else:
                if not kk or float(ang) not in kk:
                    notes.append(f"no K at {ang} deg")
                    continue
                calc, basis = effective_dp_gas(p1_psig, kk[float(ang)]), f"K={kk[float(ang)]:g} x P1abs"
            act = (actual_dp or {}).get(ang, (actual_dp or {}).get(float(ang)))
            if act is not None and act < calc:
                calc, basis = act, f"actual dP {act:g} < {basis}"
            dpe[float(ang)] = (calc, basis)
            td[float(ang)] = dynamic_torque(cval, calc)
        mast = pick(o.mast, mast_key, False, "MAST")
        limit = mast * relative_strength_pct / 100 if mast is not None else None
        peak = max([x for x in [tb, *td.values()] if x is not None], default=None)
        ok = None if limit is None or peak is None else peak < limit
        out.append(RotaryTorque(o, tb, td, dpe, limit, ok, peak, notes))
    return out
