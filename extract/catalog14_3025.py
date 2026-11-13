"""Catalog 14 3025 actuator 'Available Actuator Force' pages (B-73 to B-76) as a typed table.

These pages are not ruled tables. Rows are read from word positions: each spring row (spring range, rate,
thrust) belongs to the valve travel printed nearest to it vertically (the travel is centred on its group).

  air-to-open (spring closes):  thrust is the spring's thrust
  air-to-close (spring opens):  thrust at each supply pressure (bar) printed in the header

Writes data/catalog14/force/actuator_3025.csv; second reader: every number is found in poppler's text.

Usage:
    python extract/catalog14_3025.py data/source/d103428x012.pdf data/catalog14/force
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog14_dp import page_lines  # noqa: E402
from catalog14_tables import printed_label  # noqa: E402

ROW = re.compile(r"^(?:(?P<travel>\d+(?:\.\d+)?|120 mm)\s+)?(?P<lo>\d+(?:\.\d+)?)\s*[‐-]\s*(?P<hi>\d+(?:\.\d+)?)\s+"
                 r"(?P<rate>\d+)\s+(?P<rest>\d+(?:\s+\d+)*)$")


def lines_with_y(page) -> list[tuple[float, str]]:
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
    rows: list[list] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if rows and abs(rows[-1][0] - w["top"]) < 3:
            rows[-1][1].append(w)
        else:
            rows.append([w["top"], [w]])
    return [(top, " ".join(x["text"] for x in sorted(ws, key=lambda x: x["x0"]))) for top, ws in rows]


def main(pdf_path: str, out_dir: str) -> None:
    pdf = pdfplumber.open(pdf_path)
    out, found, total = [], 0, 0
    for pn in range(125, 145):
        page = pdf.pages[pn - 1]
        text = page.extract_text() or ""
        label = printed_label(text)
        if label not in ("B-73", "B-74", "B-75", "B-76") or "3025" not in text:
            continue
        size = re.search(r"Size (P\d+(?:-\d+)?)", text).group(1)
        page_yoke = re.search(r"Size P[\d-]+ \(([^)]*)\)", text)
        tokens = set(re.findall(r"\d+(?:\.\d+)?", " ".join(page_lines(pdf_path, pn))))
        section, yoke, bars = None, page_yoke.group(1) if page_yoke else "", []
        pending: list[dict] = []
        travels: list[tuple[float, str]] = []

        def flush():
            for row in pending:
                if not row["travel"] and travels:
                    row["travel"] = min(travels, key=lambda t: abs(t[0] - row["_y"]))[1]
                row.pop("_y")
                out.append(row)
            pending.clear()
            travels.clear()

        for y, ln in lines_with_y(page):
            ln = ln.replace("‐", "-").strip()
            m = re.search(r"Air-To-(Open|Close) \(Spring (Closes|Opens)\)(?: \(([^)]*)\))?", ln)
            if m:
                flush()
                section = "air-to-open" if m.group(1) == "Open" else "air-to-close"
                if m.group(3):
                    yoke = m.group(3)
                continue
            if re.fullmatch(r"(\d\.\d\s*){2,}", ln) and section == "air-to-close":
                bars = ln.split()
                continue
            r = ROW.match(ln)
            if r and section:
                rest = r.group("rest").split()
                for v in (r.group("lo"), r.group("hi"), r.group("rate"), *rest):
                    total += 1
                    found += v in tokens
                base = {"actuator": "3025", "size": size, "yoke_boss": yoke, "action": section,
                        "travel": r.group("travel") or "", "spring_range_bar": f"{r.group('lo')}-{r.group('hi')}",
                        "spring_rate_lb_in": r.group("rate"), "printed_label": label}
                if r.group("travel"):
                    travels.append((y, r.group("travel")))
                if section == "air-to-open":
                    pending.append({**base, "supply_bar": "", "thrust_lb": rest[0], "_y": y})
                else:
                    for bar, v in zip(bars[-len(rest):], rest):
                        pending.append({**base, "supply_bar": bar, "thrust_lb": v, "_y": y})
                continue
            if re.fullmatch(r"\d+(?:\.\d+)?|120 mm", ln) and section:
                travels.append((y, ln))
        flush()
    for r in out:
        r["travel_in"] = round(120 / 25.4, 3) if r["travel"] == "120 mm" else float(r["travel"])
    with open(Path(out_dir) / "actuator_3025.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f"3025: {len(out)} rows; second reader: {found} of {total} numbers found on their page")


if __name__ == "__main__":
    main(*sys.argv[1:])
