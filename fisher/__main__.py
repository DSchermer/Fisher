"""Command-line access to the lookups and sizing equations. Output is JSON.

    python -m fisher families
    python -m fisher find --family ED --nps 2 --characteristic linear
    python -m fisher show 122-1-8
    python -m fisher select --cv 50 --family ED --min-open 20 --max-open 80
    python -m fisher liquid --q 800 --p1 314.7 --p2 289.7 --gf 0.5 --fp 0.93
    python -m fisher gas --q 6e6 --gg 0.6 --t1 520 --p1 214.7 --p2 64.7 --k 1.31 --xt 0.137
    python -m fisher liquid-flow --cv 134.6 --p1 389.7 --p2 114.7 --gf 0.93 --fl 0.84 --pv 41.9 --ff 0.90
    python -m fisher size-valve 309-1-3 --q 6e6 --gg 0.6 --t1 520 --p1 214.7 --p2 64.7 --k 1.31
    python -m fisher steam --psia 40
    python -m fisher noise --dp 175 --p1 250 --pv 11.5 --cv 70 --km 0.7 --nps 4 --schedule 40

  Catalog 14 (actuator sizing):
    python -m fisher actuator-sliding --dp 500 --port 2.5 --actuator 585C
    python -m fisher actuator-rotary --dp 200 --valve V150 --nps 4 --angle 0
    python -m fisher actuators-for 152-1-8 --dp 300
    python -m fisher c14-tables --text "port data"
    python -m fisher rotary-actuator --valve CV500 --nps 4 --dp-shutoff 150 --p1 150 --fl 0.6 --ff 0.94 --pv 0.5 --flow forward
    python -m fisher valve-torque --valve 8532 --nps 6 --dp-shutoff 200 --p1 200 --fluid liquid --fl 0.6 --ff 0.94 --pv 0.5

  Unified dataset (data/fisher.db, docs/DATA_MODEL.md):
    python -m fisher sql "SELECT * FROM v_valve_actuator WHERE config_id = '152-1-8' AND max_dp >= 300"
    python -m fisher c14-table B_5_t1_table_2_port_data_for_single_port_valves
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from . import actuators, db, integrate, noise, reference, rotary_actuator, sizing, torque
from .catalog import Catalog
from .select import size_gas_on_valve, size_liquid_on_valve


def summary(c, opening=None) -> dict:
    d = {"config_id": c.config_id, "family": c.family, "nps": c.nps, "source": c.source,
         "title": " | ".join(x for x in (c.page_title, c.table_title, c.section) if x),
         "characteristic": c.characteristic, "flow_direction": c.flow_direction,
         "restricted_trim": c.restricted, "rated_cv": c.rated("Cv"), "warnings": len(
             [f for f in c.flags if f["severity"] != "info"])}
    if opening is not None:
        d["opening"] = opening
        d["basis"] = c.position_basis
    return d


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="fisher", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("families")
    for name in ("find", "select"):
        p = sub.add_parser(name)
        p.add_argument("--family")
        p.add_argument("--nps")
        p.add_argument("--characteristic")
        p.add_argument("--flow-direction")
        p.add_argument("--text")
        p.add_argument("--no-restricted", action="store_true")
        p.add_argument("--no-aliases", action="store_true")
        if name == "select":
            p.add_argument("--cv", type=float, required=True)
            p.add_argument("--min-open", type=float, default=20)
            p.add_argument("--max-open", type=float, default=80)
    p = sub.add_parser("show")
    p.add_argument("config_id")
    p = sub.add_parser("liquid")
    for a in ("q", "p1", "p2", "gf"):
        p.add_argument(f"--{a}", type=float, required=True)
    for a in ("fp", "fr", "fl", "pv", "ff", "pc", "n1"):
        p.add_argument(f"--{a}", type=float)
    p = sub.add_parser("gas")
    for a in ("p1", "p2", "k", "xt"):
        p.add_argument(f"--{a}", type=float, required=True)
    for a in ("q", "w", "gg", "m", "gamma1", "t1", "z", "fp"):
        p.add_argument(f"--{a}", type=float)
    p = sub.add_parser("liquid-flow")
    for a in ("cv", "p1", "p2", "gf"):
        p.add_argument(f"--{a}", type=float, required=True)
    for a in ("fl", "pv", "ff", "pc", "nu", "d", "fp"):
        p.add_argument(f"--{a}", type=float)
    p = sub.add_parser("size-valve", help="size on one catalog configuration (gas if --k is given, else liquid)")
    p.add_argument("config_id")
    for a in ("p1", "p2"):
        p.add_argument(f"--{a}", type=float, required=True)
    for a in ("k", "q", "w", "gg", "m", "gamma1", "t1", "z", "gf", "pv", "ff", "pc", "fp"):
        p.add_argument(f"--{a}", type=float)
    p = sub.add_parser("steam")
    p.add_argument("--psia", type=float)
    p.add_argument("--temp-f", type=float)
    p = sub.add_parser("actuator-sliding", help="Catalog 14 section A: sliding-stem actuators by allowable shutoff dP")
    p.add_argument("--dp", type=float, required=True)
    p.add_argument("--port", type=float, required=True)
    p.add_argument("--travel", type=float)
    for a in ("actuator", "yoke-boss", "balance", "leakage"):
        p.add_argument(f"--{a}")
    p = sub.add_parser("actuator-rotary", help="Catalog 14 section C: rotary actuators by allowable dP")
    p.add_argument("--dp", type=float, required=True)
    p.add_argument("--valve", required=True)
    p.add_argument("--nps")
    p.add_argument("--angle", type=float)
    for a in ("actuator", "text", "flow", "shaft"):
        p.add_argument(f"--{a}")
    p = sub.add_parser("c14-tables", help="search every Catalog 14 table by heading or title")
    p.add_argument("--text", default="")
    p.add_argument("--section", choices=list("ABCD"))
    sub.add_parser("c14-options", help="actuators, valves and ports available in Catalog 14")
    p = sub.add_parser("sql", help="read-only SQL against the unified dataset")
    p.add_argument("query")
    p = sub.add_parser("actuators-for", help="Catalog 14 actuators rated for a Catalog 12 valve configuration")
    p.add_argument("config_id")
    p.add_argument("--dp", type=float, default=0.0)
    p.add_argument("--angle", type=float)
    p.add_argument("--leakage")
    p.add_argument("--valve-code")
    p.add_argument("--limit", type=int)
    p = sub.add_parser("c14-table", help="one Catalog 14 table as printed")
    p.add_argument("table_id")
    p = sub.add_parser("noise", help="hydrodynamic noise, Section 3")
    for a in ("dp", "p1", "pv", "cv", "km"):
        p.add_argument(f"--{a}", type=float, required=True)
    p.add_argument("--nps", required=True)
    p.add_argument("--schedule", required=True)
    p.add_argument("--g", type=float, default=1.0)
    p.add_argument("--style", default="standard", choices=sorted(set(noise.AR_COEFFICIENTS) | noise.CAPPED_TRIMS))
    p = sub.add_parser("valve-torque", help="Catalog 14 torque method: breakout and dynamic torque for a rotary valve")
    p.add_argument("--valve", required=True, help="e.g. 8532, A11, V150/V200/V300, Control-Disk (see torque-valves)")
    p.add_argument("--nps", required=True)
    p.add_argument("--dp-shutoff", type=float, required=True)
    p.add_argument("--p1", type=float, required=True, help="inlet pressure, psig")
    p.add_argument("--fluid", choices=["liquid", "gas"], default="liquid")
    for a in ("fl", "ff", "pv", "strength"):
        p.add_argument(f"--{a}", type=float)
    for a in ("flow", "pressure-class", "construction", "variant", "b-key", "mast-key"):
        p.add_argument(f"--{a}")
    sub.add_parser("torque-valves", help="rotary valves with typed torque factors")
    p = sub.add_parser("rotary-actuator", help="valve torque (torque method) and the actuators that cover it")
    p.add_argument("--valve", required=True)
    p.add_argument("--nps", required=True)
    p.add_argument("--dp-shutoff", type=float, required=True)
    p.add_argument("--p1", type=float, required=True, help="inlet pressure, psig")
    p.add_argument("--fluid", choices=["liquid", "gas"], default="liquid")
    for a in ("fl", "ff", "pv", "supply-psig"):
        p.add_argument(f"--{a}", type=float)
    for a in ("flow", "pressure-class", "construction", "variant", "actuator", "action", "diaphragm"):
        p.add_argument(f"--{a}")
    p.add_argument("--limit", type=int, default=10)
    return ap


def run(argv) -> object:
    """Run one command and return its result (a JSON-serializable object). Used by the CLI and the UI."""
    args = parser().parse_args(argv)

    cat = Catalog.load() if args.cmd in ("families", "find", "select", "show", "size-valve", "actuators-for") else None
    if args.cmd == "families":
        out = cat.families()
    elif args.cmd in ("find", "select"):
        filters = dict(family=args.family, nps=args.nps, characteristic=args.characteristic,
                       flow_direction=args.flow_direction, text=args.text,
                       include_restricted=not args.no_restricted, include_aliases=not args.no_aliases)
        if args.cmd == "find":
            out = [summary(c) for c in cat.find(**filters)]
        else:
            out = [summary(c, op) for c, op in cat.find_valves(args.cv, args.min_open, args.max_open, **filters)]
    elif args.cmd == "show":
        c = cat.get(args.config_id)
        out = c.to_dict()
        out["page_notes"] = [{"note": k, "text": t} for k, t in cat.notes(c.page)]
    elif args.cmd == "liquid":
        r = sizing.liquid_cv(args.q, args.p1, args.p2, args.gf, n1=args.n1 or sizing.N["N1"]["gpm,psia"],
                             fp_value=args.fp or 1.0, fr=args.fr or 1.0, fl=args.fl, pv=args.pv,
                             ff_value=args.ff, pc=args.pc)
        out = {"cv": r.cv, "kv": r.kv, "steps": r.steps}
    elif args.cmd == "liquid-flow":
        r = sizing.predict_liquid_flow(args.cv, args.p1, args.p2, args.gf, fl=args.fl, pv=args.pv,
                                       ff_value=args.ff, pc=args.pc, nu=args.nu, d=args.d,
                                       fp_value=args.fp or 1.0)
        out = {"q": r.value, "steps": r.steps}
    elif args.cmd == "size-valve":
        c = cat.get(args.config_id)
        if args.k is not None:
            r = size_gas_on_valve(c, args.p1, args.p2, args.k, q=args.q, w=args.w, gg=args.gg, m=args.m,
                                  gamma1=args.gamma1, t1=args.t1, z=args.z or 1.0, fp_value=args.fp or 1.0)
        else:
            r = size_liquid_on_valve(c, args.q, args.p1, args.p2, args.gf, pv=args.pv, ff_value=args.ff,
                                     pc=args.pc, fp_value=args.fp or 1.0)
        out = r.__dict__
    elif args.cmd == "actuator-sliding":
        out = [r.to_dict() for r in actuators.sliding_stem(args.dp, args.port, args.travel, actuator=args.actuator,
                                                          yoke_boss=args.yoke_boss, balance=args.balance,
                                                          leakage=args.leakage)]
    elif args.cmd == "actuator-rotary":
        out = [r.to_dict() for r in actuators.rotary(args.dp, args.valve, args.nps, angle_deg=args.angle,
                                                    actuator=args.actuator, text=args.text, flow=args.flow,
                                                    shaft_in=args.shaft)]
    elif args.cmd == "actuators-for":
        c = cat.get(args.config_id)
        out = integrate.actuators_for_config(c, args.dp, angle_deg=args.angle, leakage=args.leakage,
                                             valve_code=args.valve_code).to_dict(args.limit)
        out["valve"] = {"family": c.family, "nps": c.nps, "source": c.source,
                        "title": " | ".join(x for x in (c.page_title, c.table_title, c.section) if x)}
    elif args.cmd == "sql":
        out = db.query(args.query)
    elif args.cmd == "c14-options":
        out = actuators.options()
    elif args.cmd == "c14-tables":
        out = actuators.search_tables(args.text, args.section)
    elif args.cmd == "c14-table":
        info = next((t for t in actuators.tables() if t["id"] == args.table_id), None)
        if info is None:
            raise KeyError(args.table_id)
        headers, rows = actuators.table(args.table_id)
        out = {**info, "headers": headers, "data": rows}
    elif args.cmd == "noise":
        out = noise.hydrodynamic_noise(dp=args.dp, p1=args.p1, pv=args.pv, cv=args.cv, km=args.km, nps=args.nps,
                                       schedule=args.schedule, g=args.g, style=args.style).__dict__
    elif args.cmd == "torque-valves":
        out = torque.valves()
    elif args.cmd == "valve-torque":
        filters = {k: v for k, v in (("flow", args.flow), ("pressure_class", args.pressure_class),
                                     ("construction", args.construction), ("variant", args.variant)) if v}
        res = torque.valve_torque_catalog(args.valve, args.nps, dp_shutoff=args.dp_shutoff, p1_psig=args.p1,
                                          fluid=args.fluid, fl=args.fl, ff=args.ff, pv_psia=args.pv,
                                          b_key=args.b_key, mast_key=args.mast_key,
                                          relative_strength_pct=args.strength or 100.0, **filters)
        out = [dataclasses.asdict(r) for r in res]
    elif args.cmd == "rotary-actuator":
        filters = {k: v for k, v in (("flow", args.flow), ("pressure_class", args.pressure_class),
                                     ("construction", args.construction), ("variant", args.variant)) if v}
        res = torque.valve_torque_catalog(args.valve, args.nps, dp_shutoff=args.dp_shutoff, p1_psig=args.p1,
                                          fluid=args.fluid, fl=args.fl, ff=args.ff, pv_psia=args.pv, **filters)
        out = []
        for r in res:
            picks = rotary_actuator.select(r.breakout_lbf_in, r.dynamic_lbf_in, valve=args.valve,
                                           actuator=args.actuator, action=args.action, flow=args.flow,
                                           attenuator=("attenuator" in (args.variant or "").lower()) or None,
                                           diaphragm_psig=args.diaphragm, supply_psig=args.supply_psig)
            out.append({"valve_torque": dataclasses.asdict(r),
                        "actuators": [dataclasses.asdict(c) for c in picks[:args.limit]]})
    elif args.cmd == "steam":
        out = reference.saturated_steam(psia=args.psia, temp_f=args.temp_f)
    else:
        r = sizing.gas_cv(args.p1, args.p2, args.k, args.xt, q=args.q, w=args.w, gg=args.gg, m=args.m,
                          gamma1=args.gamma1, t1=args.t1, z=args.z or 1.0, fp_value=args.fp or 1.0)
        out = {"cv": r.cv, "kv": r.kv, "steps": r.steps}
    return out


def main(argv=None) -> int:
    json.dump(run(argv), sys.stdout, indent=1, default=str)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
