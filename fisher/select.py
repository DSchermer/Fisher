"""Size a specific catalog valve: iterate opening <-> coefficients the way the catalog's examples do.

Gas sample problem 1 (page 2-14) sizes with the rated xT, finds the opening, re-reads xT at that
opening and repeats. These functions do that loop until the opening stops moving.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import sizing
from .catalog import Config


@dataclass
class Sized:
    config_id: str
    source: str
    required_cv: float
    opening: float | None          # None: the valve cannot pass the flow
    rated_cv: float | None
    position_basis: str = ""        # pct_travel or deg_rotation
    iterations: list[dict] = field(default_factory=list)


def _coefficient(config: Config, name: str, opening: float | None) -> float | None:
    if opening is not None:
        v = config.value_at(opening, name)
        if v is not None:
            return v
    v = config.rated(name)
    if v is not None:
        return v
    return next((val for (k, _), val in config.singles.items() if k == name), None)


def size_gas_on_valve(config: Config, p1: float, p2: float, k: float, *, max_iter: int = 20,
                      tol: float = 0.1, **service) -> Sized:
    """Required Cv and opening for a gas on one catalog configuration, using xT at the opening.

    `service` takes the gas_cv keywords: q/w, gg/m/gamma1, t1, z, fp_value.
    """
    opening, steps = None, []
    for _ in range(max_iter):
        xt = _coefficient(config, "XT", opening)
        if xt is None:
            raise ValueError(f"{config.config_id} has no XT values")
        r = sizing.gas_cv(p1, p2, k, xt, **service)
        new = config.opening_for(r.cv)
        steps.append({"xT": xt, "required_cv": r.cv, "opening": new})
        if new is None or (opening is not None and abs(new - opening) < tol):
            opening = new
            break
        opening = new
    return Sized(config.config_id, config.source, steps[-1]["required_cv"], opening, config.rated(),
                 config.position_basis, steps)


def size_liquid_on_valve(config: Config, q: float, p1: float, p2: float, gf: float, *, pv: float | None = None,
                         ff_value: float | None = None, pc: float | None = None, max_iter: int = 20,
                         tol: float = 0.1, **service) -> Sized:
    """Required Cv and opening for a liquid on one catalog configuration, using FL at the opening
    (or the valve's single FL value) for the choked-flow limit when Pv is given."""
    opening, steps = None, []
    for _ in range(max_iter):
        fl = _coefficient(config, "FL", opening) if pv is not None else None
        r = sizing.liquid_cv(q, p1, p2, gf, fl=fl, pv=pv if fl is not None else None,
                             ff_value=ff_value, pc=pc, **service)
        new = config.opening_for(r.cv)
        steps.append({"FL": fl, "required_cv": r.cv, "opening": new, "choked": r.steps.get("choked")})
        if new is None or (opening is not None and abs(new - opening) < tol):
            opening = new
            break
        opening = new
    return Sized(config.config_id, config.source, steps[-1]["required_cv"], opening, config.rated(),
                 config.position_basis, steps)
