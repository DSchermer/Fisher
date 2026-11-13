"""Write data/links/catalog12_to_catalog14.csv: for every Catalog 12 valve configuration, the Catalog 14
actuator pressure-drop ratings it links to (see fisher/integrate.py for the matching rules).

Usage:
    python extract/link_catalogs.py data/links
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fisher import Catalog, integrate  # noqa: E402


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cat = Catalog.load()
    rows = []
    for c in sorted(cat.configs.values(), key=lambda c: (c.page, [int(x) for x in c.config_id.split("-")])):
        if not c.curves or c.family == "Fd Style Modifiers":
            continue
        m = integrate.actuators_for_config(c)
        on = m.matched_on
        rows.append({
            "config_id": c.config_id, "family": c.family, "nps": c.nps, "method": m.method,
            "catalog14_valve": on.get("valve") or "", "port_in": on.get("port_in") or "",
            "travel_in": on.get("travel_in") or "", "ratings": len(m.ratings),
            "actuators": " ".join(sorted({r.actuator for r in m.ratings})),
            "max_rated_dp_psi": max((r.value for r in m.ratings), default=""),
            "catalog14_pages": " ".join(sorted({r.printed_label for r in m.ratings},
                                               key=lambda s: (s[0], float(s[2:].split(".")[0])))),
            "note": m.note,
        })
    with open(out / "catalog12_to_catalog14.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    linked = sum(1 for r in rows if r["ratings"])
    print(f"configurations {len(rows)}, linked to Catalog 14 ratings {linked}")


if __name__ == "__main__":
    main(*sys.argv[1:])
