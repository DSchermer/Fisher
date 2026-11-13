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
