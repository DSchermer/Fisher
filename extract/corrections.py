"""Inferred corrections for the Catalog 12 cells flagged by extract/validate.py (data/flags.csv).

The printed value is never changed; each correction is recorded with its basis and a confidence:

  high      the evidence leaves one reading: a typo with a single consistent reading ("0..696" -> 0.696),
            a one-character edit of the printed value that agrees with its partner coefficient and its curve,
            two adjacent cells swapped, or a Kv recomputed from a Cv that fits its curve (Kv = 0.865 Cv by
            definition, page 2-13)
  medium    derived from the partner coefficient when no single-character edit explains the error
            (e.g. Cv = Kv / 0.865, good to the Kv's printed rounding)
  estimate  no printed value says what it should be; estimated from related data (e.g. an XT read off the
            configuration's own XT-vs-Cv curve). Not applied by default.
  none      not an error (e.g. XT = 0 where the valve is closed), or no basis for a correction

Writes data/corrections.csv (and docs/CORRECTIONS.md when given).

Usage:
    python extract/corrections.py data docs/CORRECTIONS.md
"""
from __future__ import annotations

import csv
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

KV = 0.865
LO, HI = 0.85, 0.875


def num(s: str) -> float | None:
    s = re.sub(r"\(\d+\)$", "", (s or "").strip())
    if s.startswith("."):
        s = "0" + s
    try:
        return float(s)
    except ValueError:
        return None


def decimals(raw: str) -> int:
    s = raw.split("(")[0].strip()
    return len(s.split(".")[1]) if "." in s else 0


def sig_round(x: float, like: str = "") -> float:
    """Round x the way the catalog prints coefficients: three significant figures, whole numbers from 100 up."""
    if x == 0:
        return 0.0
    if abs(x) >= 100:
        return float(round(x))
    return round(x, 2 - int(math.floor(math.log10(abs(x)))))


def reproduces(candidate: str, exact: float) -> bool:
    """A typo candidate is accepted only if it is the exact value rounded as printed (+-1 in the last digit):
    Fisher computes each printed Kv from the true Cv, so the true pair reproduces to the printed rounding."""
    ulp = 10.0 ** -decimals(candidate)
    return abs(float(candidate) - exact) <= 1.01 * ulp


def consistent(cv: float, kv: float, cv_raw: str, kv_raw: str) -> bool:
    """Kv / Cv within 0.85-0.875, allowing for the printed rounding of both."""
    if cv <= 0:
        return kv == 0
    ec, ek = 0.5 * 10 ** -decimals(cv_raw), 0.5 * 10 ** -decimals(kv_raw)
    return (kv - ek) / (cv + ec) <= HI and (kv + ek) / max(cv - ec, 1e-12) >= LO


def edits(raw: str) -> set[str]:
    """Strings one keystroke away: a digit changed, a character dropped or added, two characters swapped,
    or the decimal point moved."""
    s = raw.split("(")[0].strip()
    out = set()
    digits = "0123456789"
    for i in range(len(s)):
        out.add(s[:i] + s[i + 1:])
        for d in digits:
            out.add(s[:i] + d + s[i + 1:])
    for i in range(len(s) + 1):
        for d in digits + ".":
            out.add(s[:i] + d + s[i:])
    for i in range(len(s) - 1):
        out.add(s[:i] + s[i + 1] + s[i] + s[i + 2:])
    bare = s.replace(".", "")
    for i in range(1, len(bare)):
        out.add(bare[:i] + "." + bare[i:])
    out.add(bare)
    out.discard(s)
    return {e for e in out if re.fullmatch(r"\d*\.?\d+", e) and not re.match(r"0\d", e)}


def neighbour_estimate(curve: dict[float, float], pos: float, skip: set[float]) -> float | None:
    """Log-linear interpolation from the nearest positions on each side that are not under suspicion."""
    pts = sorted((p, v) for p, v in curve.items() if p != pos and p not in skip and v and v > 0)
    left = [pv for pv in pts if pv[0] < pos]
    right = [pv for pv in pts if pv[0] > pos]
    if left and right:
        (p0, v0), (p1, v1) = left[-1], right[0]
        return math.exp(math.log(v0) + (math.log(v1) - math.log(v0)) * (pos - p0) / (p1 - p0))
    side = left[-2:] if len(left) >= 2 else right[:2] if len(right) >= 2 else None
    if side:
        (p0, v0), (p1, v1) = side
        return math.exp(math.log(v0) + (math.log(v1) - math.log(v0)) * (pos - p0) / (p1 - p0))
    return None


def dev(v: float | None, est: float | None) -> float:
    return abs(math.log(v / est)) if v and est and v > 0 and est > 0 else math.inf


def main(data_dir: str) -> None:
    d = Path(data_dir)
    flags = [f for f in csv.DictReader(open(d / "flags.csv", encoding="utf-8")) if f["severity"] != "info"]
    raw: dict[str, dict[tuple[str, str], str]] = defaultdict(dict)
    for v in csv.DictReader(open(d / "coefficients.csv", encoding="utf-8")):
        key = (v["coefficient"], v["position"] or v["position_label"])
        if key not in raw[v["config_id"]] or num(raw[v["config_id"]][key]) is None:
            raw[v["config_id"]][key] = v["value_raw"]  # a repeated label printed '- - -' must not hide the value

    def curve(cid: str, coef: str) -> dict[float, float]:
        out = {}
        for (k, p), r in raw[cid].items():
            if k == coef and re.fullmatch(r"\d+(\.\d+)?", p) and num(r) is not None:
                out[float(p)] = num(r)
        return out

    out: list[dict] = []

    def add(f, printed, corrected, basis, confidence, coefficient=None, position=None):
        out.append({"config_id": f["config_id"], "coefficient": coefficient or f["coefficient"],
                    "position": position or f["position"], "check": f["check"], "printed": printed,
                    "corrected": "" if corrected is None else f"{corrected:g}", "confidence": confidence,
                    "basis": basis})

    # ---------------------------------------------------------------- Kv / Cv mismatches, per configuration
    by_cfg: dict[str, list[dict]] = defaultdict(list)
    for f in flags:
        if f["check"] == "kv_cv_mismatch":
            by_cfg[f["config_id"]].append(f)
    for cid, fl in by_cfg.items():
        cv_c, kv_c = curve(cid, "Cv"), curve(cid, "Kv")
        flagged = {float(f["position"]) for f in fl}
        n_pos = len([p for p in cv_c if p in kv_c])
        whole_row = len(flagged) >= max(3, 0.6 * n_pos)
        done = set()
        # two adjacent flagged Kv cells swapped
        for f in fl:
            p = float(f["position"])
            q = next((x for x in sorted(flagged) if x > p), None)
            if q is None or p in done or q in done:
                continue
            rp, rq = raw[cid][("Kv", f["position"])], raw[cid][("Kv", next(k for (c, k) in raw[cid] if c == "Kv" and num(k) == q))]
            cp, cq = raw[cid][("Cv", f["position"])], raw[cid][("Cv", next(k for (c, k) in raw[cid] if c == "Cv" and num(k) == q))]
            if not consistent(num(cp), num(rp), cp, rp) and consistent(num(cp), num(rq), cp, rq) \
                    and consistent(num(cq), num(rp), cq, rp):
                fq = next(x for x in fl if float(x["position"]) == q)
                add(f, rp, num(rq), f"Kv at {p:g} and {q:g} printed swapped ({rp} / {rq})", "high")
                add(fq, rq, num(rp), f"Kv at {p:g} and {q:g} printed swapped ({rp} / {rq})", "high")
                done |= {p, q}
        for f in fl:
            p = float(f["position"])
            if p in done:
                continue
            c_raw, k_raw = raw[cid][("Cv", f["position"])], raw[cid][("Kv", f["position"])]
            c, k = num(c_raw), num(k_raw)
            est = neighbour_estimate(cv_c, p, flagged if not whole_row else set())
            est_k = neighbour_estimate({x: v / KV for x, v in kv_c.items()}, p, flagged)
            # one-character typos that reproduce the partner exactly (to the printed rounding)
            kv_typos = sorted((e for e in edits(k_raw) if c and reproduces(e, KV * c)),
                              key=lambda e: abs(float(e) - KV * c))
            cv_typos = sorted((e for e in edits(c_raw) if k and reproduces(k_raw, KV * float(e))
                               and dev(float(e), est) < 0.35), key=lambda e: dev(float(e), est))
            # which one is wrong? a typo explanation on only one side decides; otherwise the curves do
            # (with the whole Kv row inconsistent, the Cv row is taken as right)
            copied = k_raw.strip() == c_raw.strip()
            if whole_row or copied:
                kv_wrong = True
            elif kv_typos and not cv_typos:
                kv_wrong = True
            elif cv_typos and not kv_typos:
                kv_wrong = False
            else:
                kv_wrong = dev(c, est) <= dev(k / KV if k else None, est_k if est_k else est)
            d_c, d_k = dev(c, est), dev(k / KV if k else None, est_k if est_k else est)
            # decided by the curves alone, and only narrowly: say so
            narrow = not whole_row and not copied and not kv_typos and not cv_typos and \
                max(d_c, d_k) < 2 * min(d_c, d_k) + 0.05
            if kv_wrong:
                typo = kv_typos
                if typo and not whole_row:
                    add(f, k_raw, float(typo[0]), f"one-character typo: Kv printed {k_raw}, {typo[0]} agrees with "
                        f"Cv {c_raw} (0.865 x Cv = {KV * c:.4g})", "high")
                else:
                    other = whole_row and all((num(r) or 0) < 1 for (kk, _), r in raw[cid].items() if kk == "Kv") \
                        and max(cv_c.values()) > 5
                    note = (" (the printed 'Kv' row, 0.1-0.5 against Cv up to "
                            f"{max(cv_c.values()):g}, is probably another coefficient under the wrong label)" if other else
                            " (the whole Kv row is inconsistent with the Cv row)" if whole_row else
                            f" (the Kv cell repeats the Cv, {c_raw})" if copied else "")
                    add(f, k_raw, sig_round(KV * c), f"Kv = 0.865 x Cv {c_raw} (page 2-13); the printed Cv fits "
                        f"its curve{note}" + ("; close call: Cv and Kv fit their curves about equally" if narrow
                                              else ""), "medium" if narrow else "high")
            else:
                typo = cv_typos
                if typo:
                    worse = dev(float(typo[0]), est) > dev(c, est) + 0.1
                    add(f, c_raw, float(typo[0]), f"one-character typo: Cv printed {c_raw}, {typo[0]} reproduces "
                        f"Kv {k_raw} exactly (0.865 x {typo[0]} = {KV * float(typo[0]):.4g})"
                        + ("; but the printed Cv fits its curve better" if worse else ""),
                        "medium" if worse else "high", coefficient="Cv")
                else:
                    add(f, c_raw, sig_round(k / KV), f"Cv = Kv {k_raw} / 0.865; the printed Cv breaks its curve "
                        f"and the Kv fits it", "medium", coefficient="Cv")

    # ---------------------------------------------------------------- parse errors and out-of-range values
    for f in flags:
        if f["check"] == "kv_cv_mismatch":
            continue
        cid, coef, pos = f["config_id"], f["coefficient"], f["position"]
        m = re.search(r"printed as '(.*)'$|= (.*)$", f["detail"])
        printed = (m.group(1) if m.group(1) is not None else m.group(2)) if m else raw[cid].get((coef, pos), "")
        c_curve = curve(cid, coef)
        p = float(pos) if re.fullmatch(r"\d+(\.\d+)?", pos) else None
        est = neighbour_estimate(c_curve, p, set()) if p is not None else None
        if f["check"] == "parse_error":
            fixed = re.sub(r"\.{2,}", ".", printed)
            fixed = ("0" + fixed if fixed.startswith(".") else fixed).rstrip(".")
            if num(fixed) is not None and fixed.count(".") <= 1:
                add(f, printed, num(fixed), f"stray decimal point: '{printed}' read as {fixed}"
                    + (f" (neighbours suggest {est:.3g})" if est else ""), "high")
            else:
                cands = sorted((e for e in edits(printed.replace("..", ".")) | edits(printed)
                                if num(e) is not None and 0 < num(e) <= 1), key=lambda e: dev(num(e), est))
                if cands and est:
                    add(f, printed, num(cands[0]), f"'{printed}' has two decimal points; of the one-character "
                        f"readings, {cands[0]} is closest to its neighbours ({est:.3g})", "medium")
                else:
                    add(f, printed, None, "unreadable; no basis for a reading", "none")
            continue
        val = num(printed)
        cv_here = num(raw[cid].get(("Cv", pos), ""))
        if coef == "XT" and val == 0 and cv_here == 0:
            add(f, printed, val, "not an error: Cv is 0 at this position (the valve is closed), so XT = 0", "none")
        elif coef == "XT" and val is not None and val > 1 and re.fullmatch(r"\d{3}", printed):
            cand = float("0." + printed)
            add(f, printed, cand, f"'0.' missing: {printed} read as {cand:g} (neighbours suggest {est:.3g})",
                "high" if dev(cand, est) < 0.2 else "medium")
        elif coef == "XT" and p is None and val is not None and val > 1 and num(raw[cid].get(("Cv", pos), "")) == val:
            # the XT cell repeats the Cv: estimate XT where the main curve reaches this Cv
            cvc, xtc = curve(cid, "Cv"), curve(cid, "XT")
            pts = sorted(cvc.items())
            x = None
            for (p0, v0), (p1, v1) in zip(pts, pts[1:]):
                if v0 <= val <= v1 and p0 in xtc and p1 in xtc:
                    t = (val - v0) / (v1 - v0) if v1 != v0 else 0
                    x = xtc[p0] + (xtc[p1] - xtc[p0]) * t
                    break
            add(f, printed, round(x, 3) if x else None,
                f"the XT cell repeats the Cv ({printed}); estimated from this configuration's XT at the opening "
                f"where its Cv is {printed}" if x else "the XT cell repeats the Cv; no basis for an estimate",
                "estimate" if x else "none")
        elif coef == "FL" and printed.strip() in ("0.", "0"):
            page, table, block = cid.split("-")
            sib = []
            for nb in (int(block) - 1, int(block) + 1):
                vals = [num(r) for (k, _), r in raw.get(f"{page}-{table}-{nb}", {}).items() if k == "FL" and num(r)]
                if vals:
                    sib.append((f"{page}-{table}-{nb}", vals[0]))
            if len(sib) == 2:
                est_fl = round(sum(v for _, v in sib) / 2, 2)
                add(f, printed, est_fl, f"FL printed as '0.' (digits missing); estimated as the mean of the adjacent "
                    f"sizes in the same table ({sib[0][0]}: {sib[0][1]:g}, {sib[1][0]}: {sib[1][1]:g})", "estimate")
            else:
                add(f, printed, None, "FL printed as '0.': the digits are missing", "none")
        else:
            add(f, printed, None, f"{coef} = {printed} is outside (0, 1]; it may be genuine (XT above 1 means the "
                "valve does not choke at any pressure drop ratio) or a typo with no single reading", "none")
    with open(d / "corrections.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    from collections import Counter
    print(f"{len(out)} corrections for {len(flags)} flagged cells: "
          f"{dict(Counter(r['confidence'] for r in out))}")




def write_doc(data_dir: str, doc_path: str) -> None:
    """docs/CORRECTIONS.md: every flagged cell, its printed value, the inferred value and the evidence."""
    from collections import Counter
    rows = list(csv.DictReader(open(Path(data_dir) / "corrections.csv", encoding="utf-8")))
    cfg = {r["config_id"]: r for r in csv.DictReader(open(Path(data_dir) / "configs.csv", encoding="utf-8"))}
    n = Counter(r["confidence"] for r in rows)
    lines = ["# Corrections to Catalog 12 errors", "",
             "Generated by `extract/corrections.py`. Every cell `extract/validate.py` flags (Kv/Cv mismatch, out of "
             "range, unreadable) is printed that way in the catalog (confirmed by a second PDF reader), so these are "
             "catalog errors, not extraction errors. Emerson has not published the true values; these are inferred "
             "from the catalog's own evidence:", "",
             "- Kv is defined as 0.865 x Cv (Catalog 12 page 2-13), and Fisher computes each printed Kv from the true "
             "Cv, so the true pair reproduces to the printed rounding;",
             "- a one-character typo (digit changed, dropped, added or swapped; decimal point moved) that makes the "
             "pair reproduce exactly is accepted as the explanation;",
             "- otherwise the value that breaks its own curve (compared with its neighbours) is the wrong one.", "",
             f"Confidence: **high** {n['high']}, **medium** {n['medium']}, **estimate** {n['estimate']}, "
             f"**none** {n['none']}. The tools apply high and medium by default (`Catalog.load(corrections=True)`); "
             "`corrections='all'` adds estimates, `corrections=False` gives every value as printed. "
             "The printed value is always kept (`Config.raw`, `flow_coefficient.value_raw`).", "",
             "| config | page | coefficient | position | printed | corrected | confidence | basis |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        c = cfg.get(r["config_id"], {})
        lines.append(f"| {r['config_id']} | {c.get('printed_label', '')} | {r['coefficient']} | {r['position']} | "
                     f"{r['printed']} | {r['corrected']} | {r['confidence']} | {r['basis'].replace('|', '/')} |")
    Path(doc_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
    if len(sys.argv) > 2:
        write_doc(sys.argv[1], sys.argv[2])
