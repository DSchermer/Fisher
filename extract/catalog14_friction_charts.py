"""Catalog 14 piston ring friction charts as slopes (friction = slope x pressure drop).

Figure 4 (page B-18), Fisher EHD & HPD graphite piston rings: vector lines in the PDF. Each plotted line runs
from the origin; its slope is read exactly from the line's end point, on axes calibrated from the printed
tick labels. Labels (PDF text) are matched to lines by the height of the line end at the right edge, or the
top edge for lines leaving through the top.

Figure 4A (page B-18.1), Fisher TBX & CVX metal piston rings: a raster image. Rendered at 300 dpi, grid lines
removed; every remaining dark pixel gives friction / pressure drop, and the peaks of that slope histogram
are the lines. Matched to labels in the same order. APPROXIMATE (about +-3%); check in docs/MORNING.md.

Writes data/catalog14/force/piston_ring_friction.csv.

Usage:
    python extract/catalog14_friction_charts.py data/source/d103428x012.pdf data/catalog14/force
"""
from __future__ import annotations

import csv
import re
import sys
import tempfile
from pathlib import Path

import numpy as np
import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from digitize_charts import DPI, _groups, render  # noqa: E402


def _split_labels(ws: list[dict]) -> list[tuple[str, float]]:
    """Words on one text line, split where a gap of more than 12 points separates two labels."""
    parts: list[list[dict]] = []
    for w in ws:
        if parts and w["x0"] - parts[-1][-1]["x1"] < 12:
            parts[-1].append(w)
        else:
            parts.append([w])
    return [(" ".join(w["text"] for w in p), p[0]["x0"]) for p in parts]


def port_labels(page, x_min: float, y_lo: float, y_hi: float) -> list[tuple[float, float, str]]:
    """(x, y, label) for each 'IN PORT' label in the chart area, continuation lines joined."""
    rows: dict[int, list] = {}
    for w in page.extract_words():
        if y_lo < w["top"] < y_hi and w["x0"] > x_min:
            rows.setdefault(round(w["top"]), []).append(w)
    out = []
    for top in sorted(rows):
        ws = sorted(rows[top], key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in ws)
        if out and out[-1][2].rstrip().endswith("&") and top - out[-1][1] < 12:
            out[-1][2] += " " + text  # "2.875 IN PORT (EHD &" / "3.625 IN PORT (HPD)": one line, two ports
            continue
        for w_text, x in _split_labels(ws):
            if re.match(r"^\d+(\.\d+)?-?\s*IN\b", w_text):
                out.append([x, (ws[0]["top"] + ws[0]["bottom"]) / 2, w_text])
            elif w_text.startswith(("PORT", "(")) and out:
                near = min((o for o in out if top - o[1] < 12), key=lambda o: abs(o[0] - x), default=None)
                if near is not None:
                    near[2] += " " + w_text  # a label wrapped onto the next line ("16.7 IN" / "PORT")
    return [tuple(o) for o in out]


def ports_in(label: str) -> list[tuple[float, str]]:
    """'2.875 IN PORT (EHD & 3.625 IN PORT (HPD)' -> [(2.875, 'EHD'), (3.625, 'HPD')]."""
    out = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)-?\s*IN\.?\s*PORT(?:\s*\(([A-Z]+)(?:\s*&|\s*(?:or|OR)\s*([A-Z]+))?\)?)?", label):
        out.append((float(m.group(1)), m.group(2) or ""))
        if m.group(3):
            out.append((float(m.group(1)), m.group(3)))
    return out


def figure_4(pdf) -> list[dict]:
    page = pdf.pages[53]  # B-18
    ticks_x = sorted((float(w["text"]), (w["x0"] + w["x1"]) / 2) for w in page.extract_words()
                     if 505 < w["top"] < 516 and re.fullmatch(r"\d000", w["text"]))
    ticks_y = sorted((float(w["text"]), (w["top"] + w["bottom"]) / 2) for w in page.extract_words()
                     if 320 < w["top"] < 495 and 300 < w["x0"] < 340 and re.fullmatch(r"\d{3,4}", w["text"]))
    ax = np.polyfit([t[1] for t in ticks_x], [t[0] for t in ticks_x], 1)  # page x -> psi
    ay = np.polyfit([t[1] for t in ticks_y], [t[0] for t in ticks_y], 1)  # page y -> lb
    lines = [ln for ln in page.lines if 300 < ln["top"] < 520 and ln["x0"] > 290 and ln.get("linewidth", 0) > 0.8]
    labels = port_labels(page, 420, 315, 500)
    right = sorted((ln for ln in lines if ln["x1"] > 485), key=lambda ln: ln["top"])
    top = sorted((ln for ln in lines if ln["x1"] <= 485), key=lambda ln: ln["x1"])
    lab_right = sorted((lb for lb in labels if lb[0] > 480), key=lambda lb: lb[1])
    lab_top = sorted((lb for lb in labels if lb[0] <= 480), key=lambda lb: lb[0])
    out = []
    for group, labs in ((right, lab_right), (top, lab_top)):
        if len(group) != len(labs):
            raise RuntimeError(f"figure 4: {len(group)} lines but {len(labs)} labels")
        for ln, lb in zip(group, labs):
            dp, f = float(np.polyval(ax, ln["x1"])), float(np.polyval(ay, ln["top"]))
            for port, valve in ports_in(lb[2]):
                out.append({"figure": "4", "valves": valve or "EHD, HPD", "rings": "graphite", "port_in": port,
                            "slope_lb_per_psi": round(f / dp, 5), "end_dp_psi": round(dp), "end_friction_lb": round(f),
                            "label": lb[2], "method": "vector", "printed_label": "B-18"})
    return out


def figure_4a(pdf, pdf_path: str) -> list[dict]:
    page = pdf.pages[54]  # B-18.1
    img_box = next(i for i in page.images if i["x1"] - i["x0"] > 150)
    with tempfile.TemporaryDirectory() as tmp:
        img = render(pdf_path, 55, Path(tmp))
    s = DPI / 72
    x0, y0, x1, y1 = (int(v * s) for v in (img_box["x0"], img_box["top"], img_box["x1"], img_box["bottom"]))
    sub = img[y0:y1, x0:x1]
    h = _groups(np.where(sub.mean(1) > 0.35)[0])
    v = _groups(np.where(sub.mean(0) > 0.35)[0])
    left, right, top_y, bottom = v[0], v[-1], h[0], h[-1]
    m = sub.copy()
    for yy in h:
        m[int(yy) - 3:int(yy) + 4, :] = False
    for xx in v:
        m[:, int(xx) - 3:int(xx) + 4] = False
    m[:, int(right) + 2:] = False
    m[:int(top_y) - 2, :] = False
    ys, xs = np.nonzero(m)
    dp = (xs - left) / (right - left) * 4000.0
    f = (bottom - ys) / (bottom - top_y) * 5000.0
    keep = (dp > 400) & (f > 300) & (f < 5000) & (dp < 4000)
    slope = f[keep] / dp[keep]
    hist, edges = np.histogram(np.log(slope), bins=np.arange(np.log(0.15), np.log(4.5), 0.004))
    smooth = np.convolve(hist, np.ones(3) / 3, mode="same")
    peaks = [i for i in range(2, len(smooth) - 2) if smooth[i] == max(smooth[i - 2:i + 3]) and smooth[i] > 25]
    slopes = sorted((float(np.exp((edges[i] + edges[i + 1]) / 2)) for i in peaks), reverse=True)
    labels = port_labels(page, 90, 140, 345)
    lab_top = sorted((lb for lb in labels if lb[1] < 185), key=lambda lb: lb[0])
    lab_right = sorted((lb for lb in labels if lb[1] >= 185), key=lambda lb: lb[1])
    steep = [sl for sl in slopes if sl * 4000 > 5000]
    flat = [sl for sl in slopes if sl * 4000 <= 5000]
    out = []
    ok = len(steep) == len(lab_top) and len(flat) == len(lab_right)
    for group, labs in ((steep, lab_top), (flat, lab_right)):
        for i, sl in enumerate(group):
            lb = labs[i] if i < len(labs) else (0, 0, "")
            for port, _ in ports_in(lb[2]) or [(None, "")]:
                out.append({"figure": "4A", "valves": "TBX, CVX", "rings": "metal", "port_in": port,
                            "slope_lb_per_psi": round(sl, 4), "end_dp_psi": "", "end_friction_lb": "",
                            "label": lb[2], "method": "raster" + ("" if ok else " (labels not matched one to one)"),
                            "printed_label": "B-18.1"})
    print(f"figure 4A: {len(steep)}+{len(flat)} lines, {len(lab_top)}+{len(lab_right)} labels"
          + ("" if ok else " -- MISMATCH, check by hand"))
    return out


def main(pdf_path: str, out_dir: str) -> None:
    pdf = pdfplumber.open(pdf_path)
    rows = figure_4(pdf) + figure_4a(pdf, pdf_path)
    with open(Path(out_dir) / "piston_ring_friction.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} piston ring friction slopes")


if __name__ == "__main__":
    main(*sys.argv[1:])
