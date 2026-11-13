"""Section 2 reference data: saturated steam, gas k values, pipe flow areas, leakage classes,
and every other reference table as printed (unit conversions, valve flow areas)."""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

REF_DIR = Path(__file__).resolve().parent.parent / "data" / "reference"


def _rows(name: str) -> list[dict]:
    with open(REF_DIR / name, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@lru_cache(maxsize=1)
def tables() -> list[dict]:
    """Index of every extracted reference table: id, page, printed_label, title, rows, columns."""
    return _rows("index.csv")


def table(key: str) -> tuple[list[str], list[list[str]]]:
    """A reference table as printed: (headers, rows). `key` is a table id or a word from its title."""
    matches = [t for t in tables() if t["id"] == key] or \
              [t for t in tables() if key.lower() in t["title"].lower()]
    if not matches:
        raise KeyError(key)
    with open(REF_DIR / "tables" / f"{matches[0]['id']}.csv", encoding="utf-8", newline="") as fh:
        data = list(csv.reader(fh))
    return data[0], data[1:]


def _interp(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
    return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)


@lru_cache(maxsize=1)
def _steam() -> list[dict]:
    return [{k: (float(v) if k != "page" else v) for k, v in r.items()} for r in _rows("saturated_steam.csv")]


def saturated_steam(psia: float | None = None, temp_f: float | None = None) -> dict:
    """Saturated steam at a pressure (psia) or temperature (deg F), pages 2-33/2-34.

    Linear interpolation between table rows; raises ValueError outside 0.2 to 3206.2 psia.
    Returns psia, temp_f, steam_density_lb_ft3, water_specific_gravity, source.
    """
    if (psia is None) == (temp_f is None):
        raise ValueError("give exactly one of psia or temp_f")
    key, x = ("psia", psia) if psia is not None else ("temp_f", temp_f)
    rows = _steam()
    if not rows[0][key] <= x <= rows[-1][key]:
        raise ValueError(f"{key}={x} is outside the table ({rows[0][key]} to {rows[-1][key]})")
    for a, b in zip(rows, rows[1:]):
        if a[key] <= x <= b[key]:
            out = {k: _interp(x, a[key], b[key], a[k], b[k])
                   for k in ("psia", "temp_f", "steam_density_lb_ft3", "water_specific_gravity")}
            out["source"] = f"Fisher Catalog 12, page {a['page']}"
            return out
    raise AssertionError("unreachable")


def specific_heat_ratio(gas: str) -> float:
    """k for a gas from Table 1, page 2-37 (e.g. "Air" -> 1.40)."""
    _, rows = table("Specific Heat Ratio")
    for name, k in rows:
        if name.strip().lower() == gas.strip().lower():
            return float(k)
    raise KeyError(f"{gas!r} not in Table 1; gases: {[r[0] for r in rows]}")


def pipe_flow_area(nps: str | float, schedule: str | int) -> float | None:
    """Inside flow area of pipe, square inches (Table 11, page 2-40). None where the catalog shows ---."""
    headers, rows = table("Flow Area for Pipe, Inch2")
    col = next((i for i, h in enumerate(headers) if h.split()[-1].upper() == str(schedule).upper()), None)
    if col is None:
        raise KeyError(f"schedule {schedule!r}; available: {[h.split()[-1] for h in headers[1:]]}")
    want = str(nps).replace("-", " ").strip()
    for r in rows:
        if r[0].replace("-", " ").replace("‐", " ").strip() == want or r[0] == str(nps):
            return float(r[col]) if r[col] else None
    raise KeyError(f"NPS {nps!r} not in table")


def leakage_classes() -> list[dict]:
    """ANSI/FCI 70-2 leakage classes II-VI as printed on page 2-28."""
    return _rows("leakage_classes.csv")


def allowable_leakage(leak_class: str, *, rated_cv: float | None = None, dp_psi: float | None = None,
                      port_diameter_in: str | float | None = None) -> dict:
    """Maximum seat leakage for a test, page 2-28.

    II/III/IV: fraction of rated capacity -> returns the leakage as an equivalent Cv (fraction x rated Cv).
    V: 5e-4 mL/min per psid per inch of port diameter -> mL/min.
    VI: table by nominal port diameter -> bubbles/min and mL/min (only the listed diameters).
    """
    c = leak_class.upper().replace("CLASS", "").strip()
    row = next(r for r in leakage_classes() if r["class"] == c)
    if c in ("II", "III", "IV"):
        if rated_cv is None:
            raise ValueError("rated_cv is needed for classes II-IV")
        frac = float(row["fraction_of_rated_capacity"])
        return {"class": c, "fraction_of_rated_capacity": frac, "leakage_cv": frac * rated_cv,
                "test": row["test_conditions"], "medium": row["test_medium"]}
    if c == "V":
        if dp_psi is None or port_diameter_in is None:
            raise ValueError("dp_psi and port_diameter_in are needed for class V")
        return {"class": c, "ml_per_min": 5e-4 * dp_psi * float(port_diameter_in),
                "test": row["test_conditions"], "medium": row["test_medium"]}
    if c == "VI":
        for r in _rows("leakage_class_vi.csv"):
            if r["port_diameter_in"] == str(port_diameter_in) or (
                    isinstance(port_diameter_in, (int, float)) and r["port_diameter_in"].isdigit()
                    and float(r["port_diameter_in"]) == float(port_diameter_in)):
                return {"class": c, "bubbles_per_min": float(r["bubbles_per_minute"]),
                        "ml_per_min": float(r["ml_per_minute"]), "test": row["test_conditions"],
                        "medium": row["test_medium"]}
        raise KeyError(f"port diameter {port_diameter_in!r} is not listed for class VI")
    raise KeyError(leak_class)
