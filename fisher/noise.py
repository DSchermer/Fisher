"""Hydrodynamic (liquid) valve noise prediction, Fisher Catalog 12 Section 3 (pages 3-1 and 3-7 to 3-11).

    Non-cavitating:  SPL = SPL_dP + dSPL_Cv + dSPL_K + dSPL_Km + dSPL_G
    Cavitating:      SPL = SPL_dP + dSPL_Cv + dSPL_K + dSPL_Ar
    Prediction = the greater of the two (dBA, 1 m downstream of the outlet and 1 m from the pipe).

Where each term comes from:
  dSPL_Ar  equation on page 3-1, with coefficients a, b by valve style (exact).
  dSPL_K   table on page 3-9 (exact).
  SPL_dP, dSPL_Cv, dSPL_Km, dSPL_G   charts on pages 3-8 to 3-11, digitized as straight lines on the
           chart axes (data/reference/noise_chart_fits.csv, scatter 0.1-0.4 dB). These are APPROXIMATE
           and only valid inside each chart's range.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from functools import lru_cache

from . import reference

# Page 3-1: dSPL_Ar = a - b (Km / Ar) + 10 log10(1/Ar - 1), Ar = dP / (P1 - Pv)
AR_COEFFICIENTS = {
    "standard": (14.4, 18.8),
    "cavitrol_iii_1_stage": (9.4, 18.8),
    "rotary_attenuator": (9.4, 22.6),
}
# Page 3-7: Cavitrol III two- and three-stage and Cavitrol IV trims never exceed 90 dBA.
CAPPED_TRIMS = {"cavitrol_iii_2_stage", "cavitrol_iii_3_stage", "cavitrol_iv"}
CAP_DBA = 90.0


@lru_cache(maxsize=1)
def _fits() -> dict[str, dict]:
    with open(reference.REF_DIR / "noise_chart_fits.csv", encoding="utf-8", newline="") as fh:
        return {r["term"]: {k: (float(v) if k not in ("term", "page", "x") else v) for k, v in r.items()}
                for r in csv.DictReader(fh)}


def _chart(term: str, x: float) -> float:
    f = _fits()[term]
    if not f["x_min"] <= x <= f["x_max"]:
        raise ValueError(f"{term}: {x} is outside the chart range {f['x_min']:g} to {f['x_max']:g} "
                         f"(page {f['page']})")
    return f["slope"] * math.log10(x) + f["intercept"]


def spl_dp(dp: float, cavitating: bool) -> float:
    """Base SPL from pressure drop, psi (chart, page 3-8)."""
    return _chart("SPL_dP_cavitating" if cavitating else "SPL_dP_noncavitating", dp)


def dspl_cv(cv: float) -> float:
    """Correction for the required liquid sizing coefficient (chart, page 3-9)."""
    return _chart("dSPL_Cv", cv)


def dspl_km(km: float) -> float:
    """Correction for the recovery coefficient Km, non-cavitating service (chart, page 3-10)."""
    return _chart("dSPL_Km", km)


def dspl_g(g: float) -> float:
    """Correction for specific gravity, non-cavitating service; 0 for water (chart, page 3-11, range 0.3-3)."""
    return 0.0 if g == 1.0 else _chart("dSPL_G", g)


def dspl_k(nps: str | float, schedule: str | int) -> float:
    """Pipe wall correction by nominal pipe size and schedule (table, page 3-9)."""
    headers, rows = reference.table("Delta SPL K")
    col = next((i for i, h in enumerate(headers) if h.split()[-1].upper() == str(schedule).upper()), None)
    if col is None:
        raise KeyError(f"schedule {schedule!r}; available: {[h.split()[-1] for h in headers[1:]]}")
    for r in rows:
        if r[0].replace("‐", "-") == str(nps):
            if not r[col]:
                raise KeyError(f"no value for NPS {nps} schedule {schedule} (--- in the catalog)")
            return float(r[col])
    raise KeyError(f"NPS {nps!r} not in table")


def application_ratio(dp: float, p1: float, pv: float) -> float:
    """Ar = dP / (P1 - Pv)."""
    return dp / (p1 - pv)


def dspl_ar(ar: float, km: float, style: str = "standard") -> float:
    """Correction for application ratio and recovery coefficient (equation, page 3-1)."""
    if not 0 < ar < 1:
        raise ValueError("Ar must be between 0 and 1 (dP < P1 - Pv)")
    a, b = AR_COEFFICIENTS[style]
    return a - b * km / ar + 10 * math.log10(1 / ar - 1)


@dataclass
class NoiseResult:
    spl_dba: float
    governing: str
    non_cavitating: dict = field(default_factory=dict)
    cavitating: dict = field(default_factory=dict)
    note: str = ""


def hydrodynamic_noise(*, dp: float, p1: float, pv: float, cv: float, km: float, nps: str | float,
                       schedule: str | int, g: float = 1.0, style: str = "standard",
                       dspl_k_value: float | None = None) -> NoiseResult:
    """Predicted A-weighted SPL for liquid flow (page 3-7). Pressures psia, dP psi.

    `style`: "standard", "cavitrol_iii_1_stage", "rotary_attenuator" (the page 3-1 coefficients), or one of
    "cavitrol_iii_2_stage", "cavitrol_iii_3_stage", "cavitrol_iv" (standard coefficients, capped at 90 dBA,
    since those trims prevent cavitation). Pass `dspl_k_value` to override the table (e.g. insulation).
    """
    k = dspl_k_value if dspl_k_value is not None else dspl_k(nps, schedule)
    nc = {"SPL_dP": spl_dp(dp, False), "dSPL_Cv": dspl_cv(cv), "dSPL_K": k,
          "dSPL_Km": dspl_km(km), "dSPL_G": dspl_g(g)}
    nc["SPL"] = sum(nc.values())
    ar = application_ratio(dp, p1, pv)
    coeff_style = style if style in AR_COEFFICIENTS else "standard"
    cav = {"SPL_dP": spl_dp(dp, True), "dSPL_Cv": nc["dSPL_Cv"], "dSPL_K": k,
           "dSPL_Ar": dspl_ar(ar, km, coeff_style)}
    cav["SPL"] = sum(cav.values())
    cav["Ar"] = ar
    governing = "cavitating" if cav["SPL"] > nc["SPL"] else "non-cavitating"
    spl, note = max(cav["SPL"], nc["SPL"]), ""
    if style in CAPPED_TRIMS and spl > CAP_DBA:
        spl, note = CAP_DBA, "capped at 90 dBA for this trim (page 3-7)"
    return NoiseResult(spl, governing, nc, cav, note)
