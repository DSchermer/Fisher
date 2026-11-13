"""ISA/IEC control valve sizing equations, as printed in Fisher Catalog 12, Section 2.

Plain, deterministic functions. Default units are US customary:
gpm, scfh, lb/h, psia, inches, deg R, lb/ft3, centistokes.
For other units, pass the matching constant from `N` (Catalog 12 Table 2, page 2-3).

References are to Catalog 12 printed page numbers.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# Catalog 12 Table 2, Equation Constants (page 2-3). Pressures absolute; pressure base 14.7 psia.
N = {
    "N1": {"m3/h,kPa": 0.0865, "m3/h,bar": 0.865, "gpm,psia": 1.00},
    "N2": {"mm": 0.00214, "in": 890},
    "N4": {"m3/h": 76000, "gpm": 17300},
    "N5": {"mm": 0.00241, "in": 1000},
    "N6": {"kg/h,kPa,kg/m3": 2.73, "kg/h,bar,kg/m3": 27.3, "lb/h,psia,lb/ft3": 63.3},
    "N7": {"m3/h,kPa,K,0C": 3.94, "m3/h,bar,K,0C": 394, "m3/h,kPa,K,15.5C": 4.17,
           "m3/h,bar,K,15.5C": 417, "scfh,psia,R,60F": 1360},
    "N8": {"kg/h,kPa,K": 0.948, "kg/h,bar,K": 94.8, "lb/h,psia,R": 19.3},
    "N9": {"m3/h,kPa,K,0C": 21.2, "m3/h,bar,K,0C": 2120, "m3/h,kPa,K,15.5C": 22.4,
           "m3/h,bar,K,15.5C": 2240, "scfh,psia,R,60F": 7320},
}
KV_PER_CV = 0.865  # Kv = 0.865 Cv (page 2-13)

# Catalog 12 Table 3, Reynolds number factor FR for transitional flow (page 2-7).
# Columns: FR, Rev for valve size selection, flow rate prediction, pressure drop prediction.
# "Linear interpolation between listed values is satisfactory."
FR_TABLE = [
    (0.284, 56, 106, 30), (0.32, 66, 117, 38), (0.36, 79, 132, 48), (0.40, 94, 149, 59),
    (0.44, 110, 167, 74), (0.48, 130, 188, 90), (0.52, 154, 215, 113), (0.56, 188, 253, 142),
    (0.60, 230, 298, 179), (0.64, 278, 351, 224), (0.68, 340, 416, 280), (0.72, 471, 556, 400),
    (0.76, 620, 720, 540), (0.80, 980, 1100, 870), (0.84, 1560, 1690, 1430), (0.88, 2470, 2660, 2300),
    (0.92, 4600, 4800, 4400), (0.96, 10200, 10400, 10000), (1.00, 40000, 40000, 40000),
]
_FR_COL = {"selection": 1, "flow": 2, "pressure_drop": 3}
# Laminar-region equations below the first table row (pages 2-7 and 2-8).
_FR_LAMINAR = {
    "selection": lambda rev: 0.019 * rev ** 0.67,
    "flow": lambda rev: 0.0027 * rev,
    "pressure_drop": lambda rev: 0.052 * rev ** 0.5,
}


# ------------------------------------------------------------------ piping geometry

def reducer_k(d: float, D: float) -> dict[str, float]:
    """Loss coefficients for concentric reducers (page 2-4).

    K1 (inlet reducer) = 0.5 (1 - d^2/D^2)^2, K2 (outlet increaser) = 1.0 (1 - d^2/D^2)^2,
    KB (Bernoulli) = 1 - (d/D)^4.
    """
    r = (1 - d ** 2 / D ** 2) ** 2
    return {"K1": 0.5 * r, "K2": 1.0 * r, "KB": 1 - (d / D) ** 4}


def sum_k(d: float, D_in: float | None = None, D_out: float | None = None) -> float:
    """ΣK = K1 + K2 + KB1 - KB2 for reducers on either side (page 2-4). None = no fitting."""
    k1 = reducer_k(d, D_in)["K1"] if D_in else 0.0
    k2 = reducer_k(d, D_out)["K2"] if D_out else 0.0
    kb1 = reducer_k(d, D_in)["KB"] if D_in else 0.0
    kb2 = reducer_k(d, D_out)["KB"] if D_out else 0.0
    return k1 + k2 + kb1 - kb2


def fp(cv: float, d: float, sigma_k: float, n2: float = N["N2"]["in"]) -> float:
    """Piping geometry factor Fp = [1 + (ΣK/N2)(Cv/d^2)^2]^-1/2 (page 2-4)."""
    return (1 + sigma_k / n2 * (cv / d ** 2) ** 2) ** -0.5


def flp(fl: float, cv: float, d: float, k1_total: float, n2: float = N["N2"]["in"]) -> float:
    """FLP = [ (K1/N2)(Cv/d^2)^2 + 1/FL^2 ]^-1/2, K1 = K1 + KB1 of the inlet fittings (page 2-4)."""
    return (k1_total / n2 * (cv / d ** 2) ** 2 + 1 / fl ** 2) ** -0.5


# ------------------------------------------------------------------ liquids

def ff(pv: float, pc: float) -> float:
    """Liquid critical pressure ratio factor FF = 0.96 - 0.28 sqrt(Pv/Pc) (page 2-4)."""
    return 0.96 - 0.28 * math.sqrt(pv / pc)


def dp_max_liquid(fl: float, p1: float, pv: float, ff_value: float,
                  fp_value: float = 1.0, flp_value: float | None = None) -> float:
    """Allowable sizing pressure drop (page 2-4).

    No fittings: ΔPmax(L) = FL^2 (P1 - FF Pv).
    With fittings: ΔPmax(LP) = (FLP/Fp)^2 (P1 - FF Pv).
    """
    if flp_value is not None:
        return (flp_value / fp_value) ** 2 * (p1 - ff_value * pv)
    return fl ** 2 * (p1 - ff_value * pv)


def reynolds(q: float, nu: float, fl: float, cv: float, d: float, fd: float = 1.0,
             n4: float = N["N4"]["gpm"], n2: float = N["N2"]["in"]) -> float:
    """Valve Reynolds number Rev = N4 Fd q / (ν sqrt(FL Cv)) [FL^2 Cv^2 / (N2 d^4) + 1]^1/4 (page 2-6)."""
    return n4 * fd * q / (nu * math.sqrt(fl * cv)) * (fl ** 2 * cv ** 2 / (n2 * d ** 4) + 1) ** 0.25


def fr_from_reynolds(rev: float, purpose: str = "selection") -> float:
    """Reynolds number factor FR from Table 3 (linear interpolation) or the laminar equation.

    purpose: "selection" (sizing), "flow" (predicting flow rate), "pressure_drop" (predicting ΔP).
    """
    col = _FR_COL[purpose]
    rows = [(r[col], r[0]) for r in FR_TABLE]
    if rev >= rows[-1][0]:
        return 1.0
    if rev < rows[0][0]:
        return min(_FR_LAMINAR[purpose](rev), rows[0][1])
    for (r0, f0), (r1, f1) in zip(rows, rows[1:]):
        if r0 <= rev <= r1:
            return f0 + (f1 - f0) * (rev - r0) / (r1 - r0)
    raise AssertionError("unreachable")


@dataclass
class Result:
    cv: float
    steps: dict = field(default_factory=dict)

    @property
    def kv(self) -> float:
        return KV_PER_CV * self.cv


def liquid_cv(q: float, p1: float, p2: float, gf: float, *, n1: float = N["N1"]["gpm,psia"],
              fp_value: float = 1.0, fr: float = 1.0, fl: float | None = None, pv: float | None = None,
              ff_value: float | None = None, pc: float | None = None, flp_value: float | None = None) -> Result:
    """Required Cv for a liquid (page 2-2): Cv = q / (N1 Fp FR) sqrt(Gf / ΔP_sizing).

    ΔP_sizing is the smaller of P1 - P2 and ΔPmax. ΔPmax is used when FL and Pv are given
    (FF from `ff_value`, or computed from Pc).
    """
    dp = p1 - p2
    steps: dict = {"dP": dp}
    if fl is not None and pv is not None:
        f = ff_value if ff_value is not None else ff(pv, pc) if pc else None
        if f is None:
            raise ValueError("give ff_value or pc to compute the allowable pressure drop")
        dpm = dp_max_liquid(fl, p1, pv, f, fp_value, flp_value)
        steps.update({"FF": f, "dP_max": dpm, "choked": dpm < dp})
        dp = min(dp, dpm)
    steps.update({"dP_sizing": dp, "Fp": fp_value, "FR": fr, "N1": n1})
    return Result(q / (n1 * fp_value * fr * math.sqrt(dp / gf)), steps)


# ------------------------------------------------------------------ gases and vapors

def fk(k: float) -> float:
    """Ratio of specific heats factor Fk = k / 1.40 (page 2-12)."""
    return k / 1.40


def xtp(xt: float, fp_value: float, cv: float, d: float, ki: float, n5: float = N["N5"]["in"]) -> float:
    """Pressure drop ratio factor with attached fittings (page 2-13).

    xTP = (xT / Fp^2) [1 + (xT Ki / N5)(Cv/d^2)^2]^-1, Ki = K1 + KB1 of the inlet fittings.
    """
    return xt / fp_value ** 2 / (1 + xt * ki / n5 * (cv / d ** 2) ** 2)


def expansion_factor(x: float, fk_value: float, xt: float) -> tuple[float, float, bool]:
    """Y = 1 - x / (3 Fk xT), with x limited to Fk xT (choked flow; Y never below 0.667) (page 2-12).

    Returns (Y, x used, choked).
    """
    limit = fk_value * xt
    choked = x >= limit
    x_used = min(x, limit)
    return 1 - x_used / (3 * fk_value * xt), x_used, choked


def gas_cv(p1: float, p2: float, k: float, xt: float, *, q: float | None = None, w: float | None = None,
           gg: float | None = None, m: float | None = None, gamma1: float | None = None,
           t1: float | None = None, z: float = 1.0, fp_value: float = 1.0, units: str = "us",
           base: str = "15.5C") -> Result:
    """Required Cv for a compressible fluid (page 2-13). Picks the equation from what is given:

      q + Gg      -> N7: Cv = q / (N7 Fp P1 Y sqrt(x / (Gg T1 Z)))
      q + M       -> N9: Cv = q / (N9 Fp P1 Y sqrt(x / (M T1 Z)))
      w + gamma1  -> N6: Cv = w / (N6 Fp Y sqrt(x P1 gamma1))
      w + M       -> N8: Cv = w / (N8 Fp P1 Y sqrt(x M / (T1 Z)))

    `xt` is xT for a valve without fittings, or xTP (see `xtp`) with fittings.
    units (Catalog 12 Table 2; every constant gives Cv):
      "us":  scfh (60 F), lb/h, psia, deg R, lb/ft3
      "kpa": m3/h, kg/h, kPa abs, K, kg/m3     "bar": the same with bar abs
    base: for metric volumetric flow, "15.5C" (standard conditions) or "0C" (normal conditions).
    """
    if units not in ("us", "kpa", "bar"):
        raise ValueError("units must be 'us', 'kpa' or 'bar'")
    if units == "us":
        keys = {"N6": "lb/h,psia,lb/ft3", "N7": "scfh,psia,R,60F", "N8": "lb/h,psia,R", "N9": "scfh,psia,R,60F"}
    else:
        if base not in ("15.5C", "0C"):
            raise ValueError("base must be '15.5C' or '0C'")
        u = {"kpa": "kPa", "bar": "bar"}[units]
        keys = {"N6": f"kg/h,{u},kg/m3", "N7": f"m3/h,{u},K,{base}", "N8": f"kg/h,{u},K", "N9": f"m3/h,{u},K,{base}"}
    x = (p1 - p2) / p1
    fk_value = fk(k)
    y, x_used, choked = expansion_factor(x, fk_value, xt)
    steps = {"x": x, "Fk": fk_value, "xT": xt, "x_sizing": x_used, "Y": y, "choked": choked, "Fp": fp_value}
    if q is not None and gg is not None:
        cv = q / (N["N7"][keys["N7"]] * fp_value * p1 * y * math.sqrt(x_used / (gg * t1 * z)))
        steps["equation"] = "N7 " + keys["N7"]
    elif q is not None and m is not None:
        cv = q / (N["N9"][keys["N9"]] * fp_value * p1 * y * math.sqrt(x_used / (m * t1 * z)))
        steps["equation"] = "N9 " + keys["N9"]
    elif w is not None and gamma1 is not None:
        cv = w / (N["N6"][keys["N6"]] * fp_value * y * math.sqrt(x_used * p1 * gamma1))
        steps["equation"] = "N6 " + keys["N6"]
    elif w is not None and m is not None:
        cv = w / (N["N8"][keys["N8"]] * fp_value * p1 * y * math.sqrt(x_used * m / (t1 * z)))
        steps["equation"] = "N8 " + keys["N8"]
    else:
        raise ValueError("give q with gg or m, or w with gamma1 or m")
    return Result(cv, steps)


def cg_from_cv(cv: float, xt: float) -> float:
    """Gas sizing coefficient for Fisher aerodynamic noise prediction: Cg = 40 Cv sqrt(xT) (page 2-13)."""
    return 40 * cv * math.sqrt(xt)


# ------------------------------------------------------------------ predicting flow and pressure drop

def predict_liquid_flow(cv: float, p1: float, p2: float, gf: float, *, n1: float = N["N1"]["gpm,psia"],
                        fp_value: float = 1.0, fl: float | None = None, pv: float | None = None,
                        ff_value: float | None = None, pc: float | None = None,
                        nu: float | None = None, d: float | None = None, fd: float = 1.0,
                        n2: float = N["N2"]["in"], n4: float = N["N4"]["gpm"]) -> "_Flow":
    """Flow through a valve of known Cv (Predicting Flow Rate, page 2-8).

    qt = N1 Fp Cv sqrt(ΔP/Gf) assuming turbulent flow; ΔP is limited to ΔPmax when FL and Pv are given.
    With viscosity `nu` (centistokes) and valve size `d`, Rev is computed from qt and q = FR qt
    (FR from the "flow rate prediction" column of Table 3).
    """
    dp = p1 - p2
    steps: dict = {"dP": dp}
    if fl is not None and pv is not None:
        f = ff_value if ff_value is not None else ff(pv, pc)
        dpm = dp_max_liquid(fl, p1, pv, f)
        steps.update({"FF": f, "dP_max": dpm, "choked": dpm < dp})
        dp = min(dp, dpm)
    qt = n1 * fp_value * cv * math.sqrt(dp / gf)
    fr = 1.0
    if nu is not None:
        if fl is None or d is None:
            raise ValueError("fl and d are needed with nu")
        rev = reynolds(qt, nu, fl, cv, d, fd, n4, n2)
        fr = fr_from_reynolds(rev, "flow")
        steps["Rev"] = rev
    steps.update({"q_turbulent": qt, "FR": fr})
    return _Flow(fr * qt, steps)


def predict_liquid_dp(q: float, cv: float, gf: float, *, n1: float = N["N1"]["gpm,psia"],
                      fp_value: float = 1.0, nu: float | None = None, fl: float | None = None,
                      d: float | None = None, fd: float = 1.0, n2: float = N["N2"]["in"],
                      n4: float = N["N4"]["gpm"]) -> "_Flow":
    """Pressure drop across a valve of known Cv at flow q (Predicting Pressure Drop, page 2-8).

    ΔP = Gf (q / (N1 Fp FR Cv))^2, FR from the "pressure drop prediction" column of Table 3.
    """
    fr, steps = 1.0, {}
    if nu is not None:
        if fl is None or d is None:
            raise ValueError("fl and d are needed with nu")
        rev = reynolds(q, nu, fl, cv, d, fd, n4, n2)
        fr = fr_from_reynolds(rev, "pressure_drop")
        steps["Rev"] = rev
    steps["FR"] = fr
    return _Flow(gf * (q / (n1 * fp_value * fr * cv)) ** 2, steps)


def predict_gas_flow(cv: float, p1: float, p2: float, k: float, xt: float, *, gg: float | None = None,
                     m: float | None = None, gamma1: float | None = None, t1: float | None = None,
                     z: float = 1.0, fp_value: float = 1.0, mass: bool = False) -> "_Flow":
    """Flow through a valve of known Cv: the page 2-13 equations solved for q (scfh) or, with mass=True, w (lb/h)."""
    unit = gas_cv(p1, p2, k, xt, q=None if mass else 1.0, w=1.0 if mass else None, gg=gg, m=m,
                  gamma1=gamma1, t1=t1, z=z, fp_value=fp_value)
    return _Flow(cv / unit.cv, unit.steps)


@dataclass
class _Flow:
    """A predicted quantity (flow rate or pressure drop) with the intermediate values used."""
    value: float
    steps: dict = field(default_factory=dict)


# ------------------------------------------------------------------ velocity (page 2-36)

G_FT_S2 = 32.2
R_UNIVERSAL = 1545.0


def sonic_velocity(k: float, molecular_weight: float, t_rankine: float) -> float:
    """c = sqrt(k g R T), R = 1545 / M; feet per second."""
    return math.sqrt(k * G_FT_S2 * R_UNIVERSAL / molecular_weight * t_rankine)


def mach_inlet(k: float, cg: float, a1: float, c1: float, dp: float, p1: float) -> float:
    """Mean inlet Mach number.

    M1 = sqrt(5.97/(k+1)) (2/(k+1))^(1/(k-1)) (1/1900)(Cg/A1) sin((3417/C1) sqrt(ΔP/P1) deg),
    A1 in square inches, C1 = Cg/Cv. The sine argument is in degrees and is capped at 90.
    """
    angle = min(3417 / c1 * math.sqrt(dp / p1), 90.0)
    return (math.sqrt(5.97 / (k + 1)) * (2 / (k + 1)) ** (1 / (k - 1)) / 1900 * cg / a1
            * math.sin(math.radians(angle)))


def mach_outlet(k: float, m1: float, a1: float, a2: float, dp: float, p1: float) -> float:
    """Mean outlet Mach number.

    M2 = { [ (1/(k-1))^2 + (M1/(1 - ΔP/P1))^2 (A1/A2)^2 (M1^2 + 2/(k-1)) ]^1/2 - 1/(k-1) }^1/2
    """
    a = 1 / (k - 1)
    inner = a ** 2 + (m1 / (1 - dp / p1)) ** 2 * (a1 / a2) ** 2 * (m1 ** 2 + 2 / (k - 1))
    return math.sqrt(math.sqrt(inner) - a)


def steam_velocity(q_lb_h: float, v_ft3_lb: float, area_in2: float) -> float:
    """Simplified steam velocity V = Q v / (25 A), feet per second."""
    return q_lb_h * v_ft3_lb / (25 * area_in2)


# ------------------------------------------------------------------ liquid-gas mixtures (page 2-30)

def gas_volume_ratio_gas(qg_scfh: float, ql_gpm: float, p1: float, t1_rankine: float) -> float:
    """Vr for a liquid-gas mixture: Vr = Qg / (284 Ql P1 / T1 + Qg)  (equation 2)."""
    return qg_scfh / (284 * ql_gpm * p1 / t1_rankine + qg_scfh)


def gas_volume_ratio_vapor(vg: float, vl: float, quality: float) -> float:
    """Vr for a liquid-vapor mixture: Vr = vg / (vg + vl (1 - x)/x)  (equation 3)."""
    return vg / (vg + vl * (1 - quality) / quality)


def mixture_dp_allow(km: float, p1: float, rc: float, pv: float) -> float:
    """Allowable liquid sizing drop for a mixture: ΔP(allow) = Km (P1 - rc Pv)."""
    return km * (p1 - rc * pv)


def mixture_cv(cvl: float, cg: float, c1: float, fm: float) -> Result:
    """Cv for a mixture: Cvr = (Cvl + Cvg)(1 + Fm), Cvg = Cg / C1  (equation 1).

    Fm comes from figure 1 on page 2-30 as a function of Vr (see fisher.reference.two_phase_fm).
    The critical pressure ratio rc for mixture_dp_allow is the liquid FF (see ff).
    """
    cvg = cg / c1
    return Result((cvl + cvg) * (1 + fm), {"Cvg": cvg, "Fm": fm})
