"""Extract the reference tables (Section 2: unit conversions, steam, gas k values, flow areas;
Section 3: the ΔSPL_K pipe correction table).

Each table is written as-is to data/reference/tables/<id>.csv, with an index in
data/reference/index.csv. The saturated steam tables are also combined into one typed
file, data/reference/saturated_steam.csv.

Usage:
    python extract/reference_tables.py data/source/d103182x012.pdf data/reference
"""
from __future__ import annotations

import csv
import re
import subprocess
import sys
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_tables import TABLE_SETTINGS, clean, parse_value  # noqa: E402

# Pages holding reference tables (PDF page numbers) and their printed labels.
PAGES = {367: "2-24", 368: "2-25", 369: "2-26", 370: "2-27", 376: "2-33", 377: "2-34",
         380: "2-37", 381: "2-38", 382: "2-39", 383: "2-40", 384: "2-41", 385: "2-42", 395: "3-9"}
DECIMAL = re.compile(r"^[–-]?\d[\d,]*\.\d+$|^\.\d+$")
STEAM_PAGES = (376, 377)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]


def expand(raw: list[list[str | None]]) -> list[list[str]]:
    """Split rows whose cells stack several values on separate lines."""
    out = []
    for row in raw:
        parts = [[re.sub(r"[–−](?=\d)", "-", clean(x)) for x in (c or "").split("\n") if clean(x)] for c in row]
        k = max((len(p) for p in parts), default=0)
        stacked_numbers = [p for p in parts if len(p) > 1 and all(
            re.fullmatch(r"-?[\d,]*\.?\d+(\(\d\))?|[-‐\s]+", x) for x in p)]
        multi = [p for p in parts if len(p) > 1]
        if k > 1 and (len(stacked_numbers) >= 2 or (stacked_numbers and all(len(p) == k for p in multi))):
            # Align stacked values line by line; a single-line cell belongs to the first line.
            # Numbers stacked in a cell are aligned line by line; a shorter text cell is a wrapped
            # label and stays whole on the first line.
            parts = [p if len(p) == k or p in stacked_numbers else ([" ".join(p)] if p else p) for p in parts]
            for j in range(k):
                out.append([p[j] if j < len(p) else "" for p in parts] + ["__stacked__" if j else ""])
        else:
            out.append([clean(c) for c in row] + [""])
    return out


def build_headers(cells: list[list[str]], n_header: int) -> list[str]:
    """Join header rows per column; a group header spreads right over the empty cells it spans."""
    rows = [list(r) for r in cells[:n_header]]
    for r in rows[:-1]:
        for c in range(1, len(r)):
            if not r[c]:
                r[c] = r[c - 1]
    out = []
    for c in range(len(cells[0])):
        parts = []
        for r in rows:
            if r[c] and (not parts or parts[-1] != r[c]):
                parts.append(r[c])
        out.append(clean(" ".join(parts)))
    return out


def title_above(page, table) -> str:
    top = table.bbox[1]
    words = [w for w in page.extract_words(keep_blank_chars=True, x_tolerance=2)
             if top - 60 < w["bottom"] <= top + 2]
    lines: dict[int, list] = {}
    for w in words:
        lines.setdefault(round(w["top"] / 3), []).append(w)
    found = ""
    for k in sorted(lines):
        text = clean(" ".join(w["text"] for w in sorted(lines[k], key=lambda w: w["x0"])))
        m = re.search(r"Table \d+\.\s.*", text)
        if m:
            found = m.group(0)
    return re.sub(r"\s{2,}.*", "", found)


def extract_table(table) -> tuple[list[str], list[list[str]]]:
    cells = expand(table.extract())
    stacked = [r.pop() == "__stacked__" for r in cells]  # line 2+ of a split cell: nothing to carry into
    keep = [c for c in range(len(cells[0])) if any(r[c] for r in cells)]
    cells = [[r[c] for c in keep] for r in cells]
    n_header = next((i for i, r in enumerate(cells) if any(DECIMAL.match(x.replace(" ", "")) for x in r)), 1)
    headers = build_headers(cells, max(n_header, 1))
    headers = [h or f"col{i}" for i, h in enumerate(headers)]
    rows, carry = [], [""] * len(headers)
    for r, is_stacked in zip(cells[n_header:], stacked[n_header:]):
        texts = [x for x in r if x]
        if not texts or re.match(r"^\d+\.\s|^Note", texts[0]):
            continue
        if not any(re.search(r"\d", x) for x in texts):
            continue  # leftover header text
        # Merged label cells (e.g. a size spanning several port sizes): carry down leading text columns.
        for c in range(len(r)):
            if r[c] and not re.fullmatch(r"[-‐\s]+", r[c]):
                carry[c] = r[c]
            elif not r[c] and c < 2 and carry[c] and not is_stacked:
                r[c] = carry[c]
        rows.append([re.sub(r"^[‐\-\s]+$", "", x) for x in r])
    return headers, rows


def confirmed_rows(pdf_path: str, page: int, rows: list[list[str]]) -> int:
    """Second reader: how many rows appear, numbers in order, on one line of poppler's pdftotext output."""
    txt = subprocess.run(["pdftotext", "-layout", "-f", str(page), "-l", str(page), pdf_path, "-"],
                         capture_output=True, text=True).stdout
    num = re.compile(r"^-?(\d*\.\d+|\d{1,3}(?:,\d{3})+|\d+)$")
    lines = [" ".join(t for t in re.sub(r"[–−](?=\d)", "-", ln).replace(",", " ").split() if num.match(t))
             for ln in txt.splitlines()]
    n = 0
    for r in rows:
        seq = " ".join(t for x in r for t in x.replace(",", " ").split() if num.match(t))
        n += any(seq in ln for ln in lines)
    return n


def main(pdf_path: str, out_dir: str) -> None:
    out = Path(out_dir)
    (out / "tables").mkdir(parents=True, exist_ok=True)
    pdf = pdfplumber.open(pdf_path)
    index, steam = [], []
    for pn, label in PAGES.items():
        page = pdf.pages[pn - 1]
        for ti, t in enumerate(page.find_tables(TABLE_SETTINGS)):
            headers, rows = extract_table(t)
            if not rows:
                continue
            title = title_above(page, t) or ("Delta SPL K, pipe wall and insulation correction" if pn == 395
                                             else f"Table on page {label}")
            if pn in STEAM_PAGES:
                title = "Saturated Steam Pressure and Temperature"
                for r in rows:
                    nums = [parse_value(x)[0] for x in r]
                    if len(nums) == 5 and None not in nums:
                        steam.append({"psia": nums[0], "temp_f": nums[2], "steam_density_lb_ft3": nums[3],
                                      "water_specific_gravity": nums[4], "page": label})
            tid = f"p{label.replace('-', '_')}_t{ti + 1}_{slug(title)}"
            with open(out / "tables" / f"{tid}.csv", "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(headers)
                w.writerows(rows)
            index.append({"id": tid, "page": pn, "printed_label": label, "title": title,
                          "rows": len(rows), "columns": len(headers),
                          "rows_confirmed": confirmed_rows(pdf_path, pn, rows)})
    with open(out / "index.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["id", "page", "printed_label", "title", "rows", "columns",
                                               "rows_confirmed"])
        w.writeheader()
        w.writerows(index)
    steam.sort(key=lambda r: r["psia"])
    with open(out / "saturated_steam.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["psia", "temp_f", "steam_density_lb_ft3", "water_specific_gravity", "page"])
        w.writeheader()
        w.writerows(steam)
    print(f"tables {len(index)}, steam rows {len(steam)}")
    for i in index:
        print(f"  {i['printed_label']:5} {i['rows_confirmed']:3}/{i['rows']:<3} rows confirmed  {i['title'][:60]}")


if __name__ == "__main__":
    main(*sys.argv[1:])
