"""Check the extracted coefficients and write data/flags.csv.

Checks (all deterministic):
  kv_cv_mismatch   Kv should be 0.85-0.875 x Cv (0.865 nominal), allowing for printed rounding.
  out_of_range     XT, FL, Fd must be in (0, 1].
  cv_decreasing    Cv drops as the valve opens (often real, e.g. 3-way valves; reported as info).
  parse_error      A printed cell could not be read as a number (catalog typos such as "0..696").

Usage:
    python extract/validate.py data
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict

KV_PER_CV = 0.865
KV_LOW, KV_HIGH = 0.85, 0.875


def ulp(raw: str) -> float:
    s = raw.split("(")[0].strip()
    return 10.0 ** -len(s.split(".")[1]) if "." in s else 1.0


def main(data_dir: str) -> None:
    values = list(csv.DictReader(open(f"{data_dir}/coefficients.csv", encoding="utf-8")))
    curves: dict[tuple[str, str], dict[float, dict]] = defaultdict(dict)
    flags = []
    for v in values:
        if v["parse_ok"] == "0":
            flags.append((v["config_id"], v["coefficient"], v["position"] or v["position_label"],
                          "parse_error", "error", f"printed as {v['value_raw']!r}"))
        if v["value"] == "":
            continue
        x = float(v["value"])
        closed = v["position"] != "" and float(v["position"]) == 0
        if v["coefficient"] in ("XT", "FL", "Fd") and not (0 < x <= 1.0) and not (closed and x == 0):
            flags.append((v["config_id"], v["coefficient"], v["position"] or v["position_label"],
                          "out_of_range", "warning", f"{v['coefficient']} = {v['value_raw']}"))
        if v["position"] != "":
            curves[(v["config_id"], v["coefficient"])][float(v["position"])] = v

    for (cid, coeff), cv_curve in curves.items():
        if coeff != "Cv":
            continue
        kv_curve = curves.get((cid, "Kv"), {})
        for pos, cv in cv_curve.items():
            kv = kv_curve.get(pos)
            if not kv:
                continue
            c, k = float(cv["value"]), float(kv["value"])
            expected = KV_PER_CV * c
            # Catalog pages use factors from 0.85 to 0.87; also allow for printed rounding.
            half = KV_PER_CV * ulp(cv["value_raw"]) / 2 + ulp(kv["value_raw"]) / 2
            if not (KV_LOW * c - half <= k <= KV_HIGH * c + half):
                flags.append((cid, "Kv", f"{pos:g}", "kv_cv_mismatch", "warning",
                              f"Cv {cv['value_raw']} -> expected Kv {expected:.3g}, printed {kv['value_raw']}"))
        pts = sorted((p, float(v["value"]), ulp(v["value_raw"])) for p, v in cv_curve.items())
        for (p0, v0, u0), (p1, v1, u1) in zip(pts, pts[1:]):
            if v1 < v0 - (u0 + u1) / 2:
                flags.append((cid, "Cv", f"{p1:g}", "cv_decreasing", "info",
                              f"Cv {v0:g} at {p0:g} -> {v1:g} at {p1:g}"))

    with open(f"{data_dir}/flags.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["config_id", "coefficient", "position", "check", "severity", "detail"])
        w.writerows(flags)

    counts: dict[str, int] = defaultdict(int)
    for f in flags:
        counts[f[3]] += 1
    pairs = sum(1 for (cid, c), cur in curves.items() if c == "Cv"
                for p in cur if p in curves.get((cid, "Kv"), {}))
    print(f"values {len(values)}, Cv/Kv pairs checked {pairs}")
    for k in sorted(counts):
        print(f"  {k}: {counts[k]}")


if __name__ == "__main__":
    main(*sys.argv[1:])
