"""Catalog 14 force method for sliding-stem valves (section B): valve body force requirements.

    Total force required = A + B + C + D        (page B-1)
      A  force to overcome static unbalance     (pages B-2/B-3; Tables 2-2H port/unbalance areas, Table 3 stem area)
      B  seat load                              (Table 4 rules, Table 5 composition-seat factors)
      C  packing friction                       (Tables 6, 6A-6D)
      D  additional forces                      (piston_ring_friction: figures 4/4A; cryogenic_seal_ring_friction)

Pressures are psig, areas square inches, lengths inches, forces pounds.
"""
from __future__ import annotations

import ast
import csv
import operator
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

FORCE_DIR = Path(__file__).resolve().parent.parent / "data" / "catalog14" / "force"


def _rows(name: str) -> list[dict]:
    with open(FORCE_DIR / name, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _f(x):
    return float(x) if x not in ("", None) else None


# ------------------------------------------------------------------ geometry (Tables 2-3)

@lru_cache(maxsize=1)
def _ports() -> list[dict]:
    return _rows("port_data.csv")


def port_geometry(port_in: float, table: str | None = None) -> dict:
    """Circumference and area of a port (Table 2, or 2C for EH and HP valves). Raises KeyError if not listed."""
    for r in _ports():
        if (table is None or r["table"] == table) and r["table"] in ("2", "2C") and abs(float(r["port_in"]) - port_in) < 1e-6:
            return {"port_in": port_in, "circumference_in": _f(r["circumference_in"]), "area_in2": _f(r["area_in2"]),
                    "source": f"Catalog 14 table {r['table']}, page {r['printed_label']}"}
    raise KeyError(f"port {port_in} in. is not in Table 2/2C")


def unbalance_areas(port_in: float, valve: str | None = None) -> list[dict]:
    """Unbalance areas listed for a port (Tables 2/2C), optionally only those naming `valve`."""
    out = []
    for r in _rows("unbalance_area.csv"):
        if abs(float(r["port_in"]) - port_in) < 1e-6 and (
                not valve or re.search(rf"(?<![\w-]){re.escape(valve)}(?![\w-])", r["applies_to"])):
            out.append({"unbalance_area_in2": float(r["unbalance_area_in2"]), "applies_to": r["applies_to"],
                        "source": f"Catalog 14 table {r['table']}, page {r['printed_label']}"})
    return out


def stem_area(stem_in: float) -> float:
    """Valve stem area, square inches (Table 3)."""
    for r in _rows("stem_area.csv"):
        if abs(float(r["stem_in"]) - stem_in) < 1e-6:
            return float(r["area_in2"])
    raise KeyError(f"stem {stem_in} in. is not in Table 3")


# ------------------------------------------------------------------ A: static unbalance (B-2, B-3)

def pressure_tends_to(balanced: bool, flow: str, action: str) -> str:
    """'open' or 'close' (figures 1 and 2, page B-2).

    flow: 'up' or 'down'; action: 'PDTC' (push-down-to-close) or 'PDTO' (push-down-to-open).
    """
    flow, action = flow.lower(), action.upper()
    opens = {(False, "up", "PDTC"), (False, "down", "PDTO"), (True, "down", "PDTC"), (True, "up", "PDTO")}
    return "open" if (balanced, flow, action) in opens else "close"


def force_unbalance(p1: float, p2: float, area_in2: float, stem_area_in2: float, *, balanced: bool,
                    flow: str, action: str) -> float:
    """Force A, pounds. `area_in2` is the port area (unbalanced plug) or unbalance area (balanced plug).

    Negative when pressure tends to close (pressure assists the actuator in closing), as on page B-3.
    """
    dp = p1 - p2
    flow, action = flow.lower(), action.upper()
    if pressure_tends_to(balanced, flow, action) == "open":
        if not balanced:
            return dp * area_in2 + p2 * stem_area_in2 if flow == "up" else dp * area_in2 - p1 * stem_area_in2
        return dp * area_in2 + p2 * stem_area_in2 if flow == "down" else dp * area_in2 - p2 * stem_area_in2
    if not balanced:
        return -(dp * area_in2 - p1 * stem_area_in2) if flow == "down" else -(dp * area_in2 + p2 * stem_area_in2)
    return -(dp * area_in2 - p1 * stem_area_in2) if flow == "up" else -(dp * area_in2 + p1 * stem_area_in2)


# ------------------------------------------------------------------ B: seat load (Tables 4, 5)

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.USub: operator.neg}


def _eval(expr: str, names: dict) -> float:
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.Name) and n.id in names:
            return names[n.id]
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        raise ValueError(f"unsupported expression: {expr}")
    return ev(ast.parse(expr, mode="eval"))


def _port_matches(spec: str, port_in: float) -> bool:
    s = spec.lower().replace("‐", "-").strip()
    if s in ("all", ""):
        return True
    m = re.match(r"([\d.]+)\s*or\s*(less|smaller)", s)
    if m:
        return port_in <= float(m.group(1)) + 1e-9
    m = re.match(r"greater than\s*([\d.]+)", s)
    if m:
        return port_in > float(m.group(1)) + 1e-9
    m = re.match(r"([\d.]+)\s*(?:-|to)\s*([\d.]+)", s)
    if m:
        return float(m.group(1)) - 1e-9 <= port_in <= float(m.group(2)) + 1e-9
    m = re.fullmatch(r"[\d.]+", s)
    return bool(m) and abs(float(s) - port_in) < 1e-6


def _valve_names(type_text: str) -> set[str]:
    return {t.strip() for t in re.split(r",|&|\band\b", type_text.replace(" (double port)", "")) if t.strip()} | \
           set(re.findall(r"[A-Z][A-Z0-9-]+", type_text))


@lru_cache(maxsize=1)
def seat_load_rules() -> list[dict]:
    return _rows("seat_load_rules.csv")


def find_seat_rules(valve: str, port_in: float, construction: str = "Metal Seat") -> list[dict]:
    """Table 4 rows for a valve type, port and seat construction."""
    return [r for r in seat_load_rules() if valve.upper() in {v.upper() for v in _valve_names(r["type"])}
            and construction.lower() in r["construction"].lower() and _port_matches(r["port_size"], port_in)]


def composition_factors(port_in: float, seat: str, flow: str, valve: str = "") -> tuple[float, float]:
    """A and B for composition seats (Table 5)."""
    group = "EZ Valves" if valve.upper().startswith("EZ") else "All Other Valves"
    for r in _rows("seat_factors.csv"):
        if r["valves"] == group and abs(float(r["port_in"]) - port_in) < 1e-6 and seat.lower() in r["seat"].lower() \
                and (r["flow"] == "Up or Down" or r["flow"].lower() == flow.lower()):
            return float(r["A"]), float(r["B"])
    raise KeyError(f"no Table 5 factors for {seat} {flow}, {port_in} in. port ({group})")


@dataclass
class SeatLoad:
    pounds: float
    per_inch: float
    leak_class: str
    equation: str
    source: str
    note: str = ""


def seat_load(valve: str, port_in: float, leak_class: str, dp_shutoff: float, *, construction: str = "Metal Seat",
              circumference_in: float | None = None, seat: str = "PTFE", flow: str = "down",
              lb_per_inch: float | None = None) -> SeatLoad:
    """Force B. Uses the Table 4 equation for the valve, construction, port and leak class, or a seat
    load you specify (`lb_per_inch`, e.g. a customer requirement)."""
    pc = circumference_in if circumference_in is not None else port_geometry(port_in)["circumference_in"]
    if lb_per_inch is not None:
        return SeatLoad(lb_per_inch * pc, lb_per_inch, leak_class, f"{lb_per_inch:g}*PC", "specified")
    want = leak_class.upper().replace("CLASS", "").strip()
    for r in find_seat_rules(valve, port_in, construction):
        for cls, eq in ((r["class_standard"], r["equation_standard"]), (r["class_optional"], r["equation_optional"])):
            classes = {c.strip() for c in re.split(r"/", re.sub(r"\(.*?\)", "", cls))}
            if want in classes and eq and eq != "---":
                expr = eq.replace("Δ", "").replace("D", "") if "Pshutoff" in eq else eq
                expr = re.sub(r"(\d)\s*(Pshutoff|PC)", r"\1*\2", expr.replace("Pshutoff", "Pshutoff"))
                expr = re.sub(r"\)\s*(PC)", r")*\1", expr)
                note = ""
                names = {"Pshutoff": dp_shutoff, "PC": pc}
                if "A" in expr:
                    a, b = composition_factors(port_in, seat, flow, valve)
                    names.update({"A": a, "B": b})
                    lb = _eval(expr, names)
                    return SeatLoad(lb, lb / pc, cls, eq, f"Catalog 14 tables 4 and 5, page {r['printed_label']}")
                if "PC" not in expr:
                    expr = f"({expr})*PC"
                    note = "Equation printed without *PC; applied per lineal inch of port circumference."
                lb = _eval(expr, names)
                return SeatLoad(lb, lb / pc, cls, eq, f"Catalog 14 table 4, page {r['printed_label']}", note)
    raise KeyError(f"Table 4 has no class {leak_class} seat load for {valve}, {construction}, {port_in} in. port")


# ------------------------------------------------------------------ C: packing friction (Tables 6-6D)

PACKINGS = {
    "PTFE": "PTFE single", "PTFE single": "PTFE single", "PTFE double": "PTFE double",
    "PTFE/composition": "PTFE/composition", "graphite": "Graphite ribbon/filament single",
    "graphite single": "Graphite ribbon/filament single", "graphite double": "Graphite ribbon/filament double",
    "ENVIRO-SEAL PTFE": "6A ENVIRO-SEAL PTFE or duplex", "ENVIRO-SEAL graphite": "6A ENVIRO-SEAL Graphite ULF",
    "ENVIRO-SEAL H2 duplex": "6A ENVIRO-SEAL H2 duplex", "HIGH-SEAL graphite ULF": "6B HIGH-SEAL Graphite ULF Graphite ULF",
    "HIGH-SEAL graphite": "6C HIGH-SEAL Graphite Graphite", "ISO-Seal PTFE": "ISO-Seal PTFE",
    "ISO-Seal graphite": "ISO-Seal Graphite",
}


def packing_names() -> list[str]:
    return sorted({r["packing"] for r in _rows("packing_friction.csv")})


def _class_matches(spec: str, pressure_class: int | None) -> bool:
    if spec == "All" or pressure_class is None:
        return spec == "All" or pressure_class is None
    s = spec.upper().replace("CL", "")
    m = re.match(r"UP TO\s*(\d+)", s)
    if m:
        return pressure_class <= int(m.group(1))
    m = re.match(r"(\d+)\s*-\s*(\d+)", s)
    if m:
        return int(m.group(1)) <= pressure_class <= int(m.group(2))
    return s.strip().isdigit() and int(s) == pressure_class


def packing_friction(stem_in: float, packing: str = "PTFE", pressure_class: int | None = None) -> dict:
    """Force C, pounds. `packing` is a key of PACKINGS or a name from packing_names()."""
    name = PACKINGS.get(packing, packing)
    hits = [r for r in _rows("packing_friction.csv") if r["packing"] == name
            and abs(float(r["stem_in"]) - stem_in) < 1e-6 and (r["pressure_class"] == "All" or _class_matches(r["pressure_class"], pressure_class))]
    if not hits:
        raise KeyError(f"no packing friction for {name}, {stem_in} in. stem, class {pressure_class}")
    if len({r["pounds"] for r in hits}) > 1 and pressure_class is None:
        raise ValueError(f"{name} friction for a {stem_in} in. stem depends on pressure class: give pressure_class")
    r = hits[0]
    return {"pounds": float(r["pounds"]), "packing": name, "source": f"Catalog 14 table {r['table']}, page {r['printed_label']}"}


# ------------------------------------------------------------------ total (B-1)

@dataclass
class ValveForces:
    pressure_tends_to: str
    A: float
    B: float
    C: float
    D: float
    closing_force: float
    opening_force: float | None
    steps: dict = field(default_factory=dict)


def valve_forces(*, p1: float, p2: float = 0.0, dp_shutoff: float | None = None, balanced: bool, flow: str,
                 action: str, area_in2: float, stem_area_in2: float, seat: SeatLoad, packing_lb: float,
                 additional_lb: float = 0.0) -> ValveForces:
    """Total force = A + B + C + D (page B-1).

    Pressure tends to close: closing force uses the (negative) A; opening force = -A + C + D, with no seat
    load (page B-3). The larger governs for every actuator except the 585C, which uses both.
    """
    a = force_unbalance(p1, p2, area_in2, stem_area_in2, balanced=balanced, flow=flow, action=action)
    ptt = pressure_tends_to(balanced, flow, action)
    closing = a + seat.pounds + packing_lb + additional_lb
    opening = (-a + packing_lb + additional_lb) if ptt == "close" else None
    return ValveForces(ptt, a, seat.pounds, packing_lb, additional_lb, closing, opening,
                       {"seat_load": seat.__dict__, "dP": p1 - p2})


# ------------------------------------------------------------------ D: additional forces (page B-18)

def piston_ring_friction(port_in: float, dp: float, *, valve: str = "EHD") -> dict:
    """Piston ring friction (force D) from figure 4 (EHD/HPD graphite rings, page B-18; vector, exact) or
    figure 4A (TBX/CVX metal rings, page B-18.1; digitized from the image, about +-3%).
    friction = slope x pressure drop; lines run from the origin."""
    v = valve.upper()
    fig = "4A" if v in ("TBX", "CVX") else "4"
    rows = [r for r in _rows("piston_ring_friction.csv") if r["figure"] == fig and r["port_in"]
            and abs(float(r["port_in"]) - port_in) < 1e-6]
    if fig == "4":
        rows = [r for r in rows if v in r["valves"].replace(" ", "").split(",")] or rows
    if not rows:
        raise KeyError(f"no figure {fig} line for a {port_in} in port ({valve})")
    r = rows[0]
    return {"force_lb": float(r["slope_lb_per_psi"]) * dp, "slope_lb_per_psi": float(r["slope_lb_per_psi"]),
            "approximate": r["method"] != "vector",
            "source": f"Fisher Catalog 14, figure {fig}, page {r['printed_label']} ({r['method']})"}


def cryogenic_seal_ring_friction(port_in: float) -> dict:
    """ET-C / EWT-C and ET / EWT Class VI: UHMWPE/R30003 cryogenic seal ring friction (page B-18):
    28 lb per lineal inch of port circumference below 8 inch ports, 34 lb/in at 8 inches and above."""
    per_in = 28.0 if port_in < 8 else 34.0
    circ = 3.141592653589793 * port_in
    return {"force_lb": per_in * circ, "lb_per_inch": per_in, "port_circumference_in": circ,
            "source": "Fisher Catalog 14, page B-18"}
