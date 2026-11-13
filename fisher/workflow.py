"""End to end: service conditions -> the Catalog 12 valves that fit -> the Catalog 14 actuators for them.

    size_application(fluid="liquid", q=800, p1=314.7, p2=289.7, gf=0.5, pv=..., pipe_in=4)

For each candidate configuration:
  1. required Cv on that valve, iterating FL (liquid) or xT (gas) at the opening as the catalog's examples do
     (fisher.select), with the piping geometry factor Fp when the pipe is larger than the valve;
  2. the opening, which must fall within min_open..max_open;
  3. checks: choked flow (liquid), hydrodynamic noise (liquid; Km = FL^2, Catalog 12 page 3-7), catalog
     corrections that touch this valve;
  4. actuators: Catalog 14 pressure drop method (sections A and C) at the shutoff pressure drop, or for rotary
     valves without a section C table, the torque method (section D) with fisher.rotary_actuator.

Every number names its catalog page. Assumptions made for missing inputs are listed in the result.
Pressures psia (dp_shutoff psi), flows gpm / scfh / lb/h, temperatures deg R for gas.
"""
from __future__ import annotations

import re

from . import integrate, noise, rotary_actuator, sizing, torque
from .catalog import Catalog, Config
from .select import size_gas_on_valve, size_liquid_on_valve

ATM = 14.7


def _fp(config: Config, pipe_in: float | None) -> tuple[float, str]:
    d = min(config.sizes) if config.sizes else None
    if not pipe_in or not d or pipe_in <= d or not config.rated():
        return 1.0, ""
    fp = sizing.fp(config.rated(), d, sizing.sum_k(d, D_in=pipe_in, D_out=pipe_in))
    return fp, f"Fp {fp:.3f} for a {d:g} in valve between {pipe_in:g} in reducers (page 2-5, rated Cv)"


def _estimate_cv(fluid: str, p1: float, p2: float, **s) -> float:
    if fluid == "liquid":
        return sizing.liquid_cv(s["q"], p1, p2, s["gf"]).cv
    return sizing.gas_cv(p1, p2, s["k"], 0.7, q=s.get("q"), w=s.get("w"), gg=s.get("gg"), m=s.get("m"),
                         gamma1=s.get("gamma1"), t1=s.get("t1"), z=s.get("z") or 1.0).cv


def _actuators(config: Config, dp_shutoff: float, limit: int) -> dict:
    m = integrate.actuators_for_config(config, dp_shutoff, angle_deg=0.0 if config.motion == "rotary" else None)
    out = {"method": "pressure drop (Catalog 14 section A/C)", "note": m.note, "options": []}
    if m.ratings:
        # the smallest rated size of each actuator type, then the next types
        def size_of(r):
            if r.actuator_size:
                return r.actuator_size
            hit = re.search(r"Size\s*(\S+)", " ".join([r.column, *map(str, r.keys.values())]))
            return hit.group(1) if hit else ""
        best = sorted(m.ratings, key=lambda r: (_num(size_of(r)), r.actuator, -r.value))
        seen = set()
        for r in best:
            if r.actuator in seen:
                continue
            seen.add(r.actuator)
            out["options"].append({"actuator": r.actuator, "size": size_of(r), "max_dp_psi": r.value,
                                   "conditions": {k: v for k, v in (("column", r.column), ("action", r.action),
                                                                    ("leakage", r.leakage)) if v},
                                   "source": f"Fisher Catalog 14, page {r.printed_label}"})
            if len(out["options"]) >= limit:
                break
        return out
    if config.motion == "rotary":
        family = config.family.replace("™", "").replace("-", " ")
        valve = next((v for v in torque.valves() if family in v.replace("/", " ").split() or v == family), None)
        if valve and config.sizes:
            try:
                tq = torque.valve_torque_catalog(valve, config.sizes[0], dp_shutoff=dp_shutoff,
                                                 p1_psig=dp_shutoff, fluid="gas",
                                                 k={a: 1.0 for a in range(0, 91, 5)})
            except (KeyError, ValueError):
                tq = []
            if tq:
                t = max(tq, key=lambda r: r.breakout_lbf_in or 0)
                picks, seen = [], set()
                for c in rotary_actuator.select(t.breakout_lbf_in, None, valve=valve):
                    if c.passes and (c.actuator, c.size, c.action) not in seen:
                        seen.add((c.actuator, c.size, c.action))
                        picks.append(c)
                picks = picks[:limit]
                none = "" if picks else "; no Catalog 14 actuator torque table names this valve"
                return {"method": "torque (Catalog 14 section D), breakout only",
                        "note": f"breakout torque {t.breakout_lbf_in:.0f} lbf-in at {dp_shutoff:g} psi shutoff "
                                f"({t.option.source}); check dynamic torque with valve_torque_catalog and the "
                                "actual flowing pressure drops" + none,
                        "options": [{"actuator": c.actuator, "size": c.size, "action": c.action,
                                     "breakout_available_lbf_in": c.breakout_available, "source": c.source}
                                    for c in picks]}
    return out


def _num(s: str) -> float:
    m = re.match(r"\d+(\.\d+)?", s or "")
    return float(m.group()) if m else 1e9


def size_application(*, fluid: str, p1: float, p2: float, q: float | None = None, w: float | None = None,
                     gf: float | None = None, pv: float | None = None, pc: float | None = None,
                     ff: float | None = None,
                     gg: float | None = None, m: float | None = None, k: float | None = None,
                     t1: float | None = None, z: float | None = None, gamma1: float | None = None,
                     pipe_in: float | None = None, schedule: str = "40", family: str | None = None,
                     motion: str | None = None, characteristic: str | None = None,
                     min_open: float = 20, max_open: float = 80, include_restricted: bool = False,
                     dp_shutoff: float | None = None, candidates: int = 5, actuators: int = 3) -> dict:
    """Valves from Catalog 12 that pass the flow between min_open and max_open, each with checks and the
    Catalog 14 actuators rated for it. Sorted by smallest body size, then opening nearest 65%."""
    if fluid not in ("liquid", "gas"):
        raise ValueError("fluid must be 'liquid' or 'gas'")
    if fluid == "liquid" and (q is None or gf is None):
        raise ValueError("liquid needs q (gpm) and gf")
    if fluid == "gas" and (k is None or (q is None and w is None)):
        raise ValueError("gas needs k and q (scfh) or w (lb/h), with gg or m and t1, or gamma1")
    assumptions = []
    if dp_shutoff is None:
        dp_shutoff = p1 - ATM
        assumptions.append(f"shutoff pressure drop = P1 gauge = {dp_shutoff:g} psi (outlet at atmosphere at shutoff)")
    if fluid == "liquid" and pv is None:
        assumptions.append("no vapor pressure given: choked flow and cavitation not checked")
    if fluid == "liquid" and pv is not None and pc is None and ff is None:
        ff = 0.96
        assumptions.append("no critical pressure given: FF = 0.96, the upper limit of 0.96 - 0.28 sqrt(Pv/Pc) "
                           "(conservative: the smallest allowable pressure drop)")
    if fluid == "gas" and pipe_in:
        assumptions.append("gas: Fp applied to Cv; the xT correction for fittings (xTP) is not applied")
    cat = Catalog.load()
    service = {"q": q, "w": w, "gf": gf, "gg": gg, "m": m, "k": k, "t1": t1, "z": z, "gamma1": gamma1}
    est = _estimate_cv(fluid, p1, p2, **service)
    hits, skipped = [], []
    for c in cat.find(family=family, characteristic=characteristic, include_restricted=include_restricted,
                      coefficient="Cv"):
        if motion and c.motion != motion or c.motion == "reference":
            continue
        rated = c.rated()
        if not rated or rated < 0.5 * est or rated > 50 * est or c.opening_for(est * 0.5) is None:
            continue
        fp, fp_note = _fp(c, pipe_in)
        try:
            if fluid == "liquid":
                s = size_liquid_on_valve(c, q, p1, p2, gf, pv=pv, pc=pc, ff_value=ff, fp_value=fp)
            else:
                s = size_gas_on_valve(c, p1, p2, k, q=q, w=w, gg=gg, m=m, gamma1=gamma1, t1=t1, z=z or 1.0,
                                      fp_value=fp)
        except (ValueError, ZeroDivisionError) as e:
            skipped.append(f"{c.config_id}: {e}")
            continue
        if s.opening is None or not (min_open <= s.opening <= max_open):
            continue
        hits.append((c, s, fp, fp_note))
    hits.sort(key=lambda h: (min(h[0].sizes) if h[0].sizes else 1e9, abs(h[1].opening - 65)))
    out, seen = [], set()
    for c, s, fp, fp_note in hits:
        key = (c.family, min(c.sizes) if c.sizes else c.nps)
        if key in seen:
            continue
        seen.add(key)
        checks, notes = {}, [fp_note] if fp_note else []
        last = s.iterations[-1]
        if fluid == "liquid":
            fl = last.get("FL")
            checks["choked"] = bool(last.get("choked")) if fl else None
            if pv is not None and not fl:
                notes.append("no FL printed for this configuration: choked flow and noise not checked")
            if pv is not None and fl:
                try:
                    nz = noise.hydrodynamic_noise(dp=p1 - p2, p1=p1, pv=pv, cv=s.required_cv, km=fl * fl,
                                                  nps=pipe_in or (min(c.sizes) if c.sizes else 1),
                                                  schedule=schedule, g=gf)
                    checks["noise_dba"] = round(nz.spl_dba, 1)
                    checks["noise_regime"] = nz.governing
                    notes.append(f"noise: Km = FL^2 = {fl * fl:.2f} (page 3-7), schedule {schedule} pipe")
                except (KeyError, ValueError):
                    pass
        else:
            checks["xT_at_opening"] = last.get("xT")
        warnings = []
        if checks.get("choked"):
            warnings.append("choked flow: the pressure drop exceeds the allowable dP (flashing or cavitation); "
                            "consider cavitation-control trim")
        if checks.get("noise_dba", 0) > 85:
            warnings.append(f"predicted noise {checks['noise_dba']:g} dBA exceeds 85 dBA")
        if c.restricted:
            notes.append("restricted trim")
        if c.corrections:
            notes.append(f"{len(c.corrections)} catalog value(s) corrected for this valve (docs/CORRECTIONS.md)")
        warn = [f for f in c.flags if f["severity"] != "info"]
        if warn:
            notes.append(f"{len(warn)} catalog flag(s) on this valve")
        out.append({"config_id": c.config_id, "family": c.family, "nps": c.nps, "motion": c.motion,
                    "characteristic": c.characteristic, "flow_direction": c.flow_direction,
                    "pressure_class": c.pressure_class, "required_cv": round(s.required_cv, 3),
                    "opening": round(s.opening, 1), "position_basis": c.position_basis, "rated_cv": s.rated_cv,
                    "fp": round(fp, 4), "checks": checks, "warnings": warnings, "notes": notes, "source": c.source,
                    "actuators": _actuators(c, dp_shutoff, actuators)})
        if len(out) >= candidates:
            break
    return {"service": {"fluid": fluid, "p1_psia": p1, "p2_psia": p2, **{k_: v for k_, v in service.items() if v is not None},
                        "pv": pv, "pipe_in": pipe_in}, "estimated_cv": round(est, 3), "dp_shutoff_psi": dp_shutoff,
            "assumptions": assumptions, "candidates": out,
            "found": len(hits), "skipped": len(skipped), "first_skip": skipped[0] if skipped else "",
            "note": "" if out else
            f"no configuration passes Cv {est:.3g} between {min_open:g} and {max_open:g} with these filters"}
