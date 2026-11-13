"""Digitize the catalog's charts.

Section 3 hydrodynamic-noise charts (pages 3-8 to 3-11) are straight lines on their axes and are
fitted; the two liquid-gas mixture charts on page 2-30 are curves and are sampled into point tables.


The charts are raster images. Each is rendered at 300 dpi, the grid lines are found and removed,
and the remaining dark pixels (the plotted line) are fitted with least squares on the chart's own
axes. Writes data/reference/noise_chart_fits.csv with the fitted coefficients and their scatter, and
data/reference/two_phase_fm.csv and two_phase_critical_dp_ratio.csv with sampled curve points.

Needs poppler-utils (pdftoppm), numpy and pillow.

Usage:
    python extract/digitize_charts.py data/source/d103182x012.pdf data/reference
"""
from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

DPI = 300


def render(pdf: str, page: int, tmp: Path) -> np.ndarray:
    out = tmp / f"p{page}"
    subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(DPI), "-gray", "-png",
                    pdf, str(out)], check=True, capture_output=True)
    png = next(tmp.glob(f"p{page}*.png"))
    return np.array(Image.open(png).convert("L")) < 128


def _groups(idx: np.ndarray) -> list[float]:
    g: list[list[int]] = []
    for v in idx:
        if g and v - g[-1][-1] <= 3:
            g[-1].append(int(v))
        else:
            g.append([int(v)])
    return [(x[0] + x[-1]) / 2 for x in g]


def curve_pixels(img: np.ndarray, box_90dpi: tuple[int, int, int, int], frac: float):
    """Crop the plot (box given at 90 dpi), find grid lines, return (h_lines, v_lines, xs, ys) of the curve."""
    s = DPI / 90
    x0, y0, x1, y1 = (int(v * s) for v in box_90dpi)
    sub = img[y0:y1, x0:x1]
    h = _groups(np.where(sub.mean(1) > frac)[0])
    v = _groups(np.where(sub.mean(0) > frac)[0])
    m = sub.copy()
    for y in h:
        m[int(y) - 3:int(y) + 4, :] = False
    for x in v:
        m[:, int(x) - 3:int(x) + 4] = False
    # The outer axes are drawn heavier than the grid, with tick marks: clear a wider band around them.
    if h and v:
        m[int(h[-1]) - 8:, :] = False
        m[:, :int(v[0]) + 8] = False
    ys, xs = np.nonzero(m)
    return h, v, xs, ys


def robust_line(x: np.ndarray, y: np.ndarray, guess, start_tol: float, tol: float, keep=None):
    sel = np.abs(y - guess(x)) < start_tol
    if keep is not None:
        sel &= keep
    for _ in range(5):
        c = np.polyfit(x[sel], y[sel], 1)
        r = y - np.polyval(c, x)
        sel = np.abs(r) < tol
        if keep is not None:
            sel &= keep
    return c[0], c[1], int(sel.sum()), float(np.std(r[sel]))


def sample_curve(xs, ys, x_of, y_of, x_lo, x_hi, step, half_window):
    """Average curve height in a small window around each x. Returns [(x, y, pixels)]."""
    X, Y = x_of(xs), y_of(ys)
    out = []
    for x in np.arange(x_lo, x_hi + 1e-9, step):
        sel = np.abs(X - x) <= half_window
        if sel.sum() >= 3:
            out.append((round(float(x), 4), float(np.median(Y[sel])), int(sel.sum())))
    return out


def two_phase_charts(pdf: str, tmp: Path, out_dir: Path) -> None:
    img = render(pdf, 373, tmp)
    # Figure 1: Fm vs gas volume ratio Vr; grid 0..1 in both directions (Fm step 0.1, Vr step 0.05).
    h, v, xs, ys = curve_pixels(img, (400, 210, 695, 445), 0.5)
    pts = sample_curve(xs, ys, lambda x: np.interp(x, [v[0], v[-1]], [0, 1]),
                       lambda y: np.interp(y, [h[0], h[-1]], [1, 0]), 0.0, 1.0, 0.02, 0.006)
    _write(out_dir / "two_phase_fm.csv", ["vr", "fm", "pixels"], pts)
    # Figure 2: dP/P1 giving 100% critical gas flow vs C1; grid C1 0..40 (2.5), ratio 0..0.60 (0.05).
    h, v, xs, ys = curve_pixels(img, (400, 520, 695, 760), 0.5)
    pts = sample_curve(xs, ys, lambda x: np.interp(x, [v[0], v[-1]], [0, 40]),
                       lambda y: np.interp(y, [h[0], h[-1]], [0.60, 0]), 10, 40, 1.0, 0.25)
    _write(out_dir / "two_phase_critical_dp_ratio.csv", ["c1", "dp_over_p1", "pixels"], pts)


def _write(path: Path, header, rows) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows([(r[0], f"{r[1]:.4f}", r[2]) for r in rows])
    print(f"{path.name}: {len(rows)} points")


def main(pdf: str, out_dir: str) -> None:
    rows = []
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        # Page 3-8: SPL_dP vs dP, two lines; y grid -10..140 dB every 5, x decades 0.1..10,000 psi.
        h, v, xs, ys = curve_pixels(render(pdf, 394, tmp), (205, 155, 595, 535), 0.6)
        dec_x = [30, 276, 531, 789, 1037, 1286] if len(h) == 31 else None
        if dec_x is None:
            raise RuntimeError("unexpected grid on page 3-8")
        L = np.interp(xs, dec_x, [-1, 0, 1, 2, 3, 4])
        D = 140 - (ys - h[0]) / (h[-1] - h[0]) * 150
        for name, guess in (("SPL_dP_cavitating", lambda l: 74 + 15 * l),
                            ("SPL_dP_noncavitating", lambda l: 37 + 20 * l)):
            slope, icpt, n, sd = robust_line(L, D, guess, 6, 1.5)
            rows.append((name, "3-8", "log10(dP psi)", slope, icpt, 0.1, 10000, n, sd))
        # Page 3-9: dSPL_Cv vs Cv; y 0..90 every 5, x decades 1..10,000.
        h, v, xs, ys = curve_pixels(render(pdf, 395, tmp), (240, 170, 560, 410), 0.6)
        L = np.interp(xs, [28, 282, 537, 790, 1044], [0, 1, 2, 3, 4])
        D = 90 - (ys - h[0]) / (h[-1] - h[0]) * 90
        slope, icpt, n, sd = robust_line(L, D, lambda l: 10 * l, 4, 1.0)
        rows.append(("dSPL_Cv", "3-9", "log10(Cv)", slope, icpt, 1, 10000, n, sd))
        # Page 3-10 (lower): dSPL_Km vs Km; y lines 15,10,5,0,-5,...; x Km 0..1.
        h, v, xs, ys = curve_pixels(render(pdf, 396, tmp), (195, 515, 615, 825), 0.5)
        K = np.interp(xs, [v[0], v[-1]], [0, 1])
        D = 10 - (ys - h[1]) / (h[3] - h[1]) * 10
        ok = K > 0.08
        slope, icpt, n, sd = robust_line(np.log10(np.clip(K, 1e-3, None)), D, lambda l: -5 * l, 1.0, 0.5, ok)
        rows.append(("dSPL_Km", "3-10", "log10(Km)", slope, icpt, 0.1, 1.0, n, sd))
        # Page 3-11: dSPL_G vs G; y lines ..., 10, 5, 0, -5, -10; x decades 0.1..10. The "usual range"
        # arrow is drawn at about -5 dB and is excluded.
        h, v, xs, ys = curve_pixels(render(pdf, 397, tmp), (265, 200, 535, 395), 0.5)
        L = np.interp(xs, [30, 456, 882], [-1, 0, 1])
        D = 10 - (ys - h[2]) / (h[6] - h[2]) * 20
        slope, icpt, n, sd = robust_line(L, D, lambda l: -5 * l, 1.2, 0.6, D > -4)
        rows.append(("dSPL_G", "3-11", "log10(G)", slope, icpt, 0.3, 3.0, n, sd))
        two_phase_charts(pdf, tmp, Path(out_dir))
    out = Path(out_dir) / "noise_chart_fits.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["term", "page", "x", "slope", "intercept", "x_min", "x_max", "pixels", "scatter_db"])
        for r in rows:
            w.writerow([r[0], r[1], r[2], f"{r[3]:.3f}", f"{r[4]:.3f}", r[5], r[6], r[7], f"{r[8]:.2f}"])
    for r in rows:
        print(f"{r[0]:22} = {r[3]:.3f} {r[2]} + {r[4]:.3f}   ({r[7]} px, scatter {r[8]:.2f} dB)")


if __name__ == "__main__":
    main(*sys.argv[1:])
