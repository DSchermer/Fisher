"""Extract flow-coefficient tables from Fisher Catalog 12 into a long-format CSV.

Deterministic: reads the PDF's ruled table cells (pdfplumber "lines" strategy),
works out what each column means from its header, and writes one row per value.

Usage:
    python extract/parse_tables.py data/source/d103182x012.pdf docs/page_inventory.csv data
"""
from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import dataclass, field

import pdfplumber

TABLE_SETTINGS = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}

DASHES = "\u2010\u2011\u2012\u2013\u2014\u2212\\-"
NULL_RE = re.compile(rf"^[{DASHES}\s]*$")
FOOTNOTE_RE = re.compile(r"\((\d+(?:\s*,\s*\d+)*)\)\s*$")
NUM_RE = re.compile(r"^[<>~]?\s*(\d{1,3}(?:,\d{3})+|\d*\.\d+|\d+\.?)$")

# Row labels that name a coefficient (label-column layouts).
LABEL_MAP = {
    "cv": "Cv", "kv": "Kv", "xt": "XT", "fl": "FL", "fd": "Fd", "kc": "Kc",
    "cvnet": "Cvnet", "kvnet": "Kvnet", "flnet": "FLnet", "xtnet": "XTnet",
    "flp": "FLP", "cg": "Cg", "cs": "Cs", "c1": "C1", "km": "Km", "fp": "FP",
    "xfz": "Xfz", "kn": "Kn",
}
# Single-value columns, matched on the start of the column header.
SCALAR_HEADER_RE = [
    (re.compile(r"^(FL|Fl)\s*net", re.I), "FLnet"),
    (re.compile(r"^(FL|Fl)\b|^FL\s*\(|^Fl\s*\(", re.I), "FL"),
    (re.compile(r"^XT\b|^xT\b|^XT\s*\(", re.I), "XT"),
    (re.compile(r"^Fd\b|^Fd\s*\(", re.I), "Fd"),
    (re.compile(r"^Kn\b", re.I), "Kn"),
    (re.compile(r"^Kc\b", re.I), "Kc"),
    (re.compile(r"^Xfz\b", re.I), "Xfz"),
]
ATTR_WORDS = re.compile(
    r"size|nps|\bdn\b|port|diameter|bore|travel|trim|char|direction|stage|seal|disk|"
    r"cage|ring|plug|style|unbal|throttl|actuator|construction|type|seat|liner|orifice|"
    r"class|rating|model|ball|attenuator|insert|body|shaft|configuration|pattern|description",
    re.I,
)
CHARACTERISTICS = [
    "Modified Equal Percentage", "Equal Percentage", "Modified Linear", "Quick Opening",
    "Modified Parabolic", "Linear", "Characterized",
]
# Row labels whose cells hold text, not numbers (HP pages: which trim stage is active).
TEXT_LABELS = {"holetype": "HoleType"}
FLOW_DIRECTIONS = [
    "Flow Up", "Flow Down", "Forward Flow", "Reverse Flow", "Flow Up or Down",
    "Flow Tends to Open", "Flow Tends to Close", "Flow to Open", "Flow to Close",
]


def clean(text: str | None) -> str:
    if text is None:
        return ""
    text = re.sub(r"\(cid:\d+\)", "", text)  # (R)/(TM)/degree glyphs from symbol fonts
    return re.sub(r"\s+", " ", text.replace("\u2010", "-")).strip()


def parse_value(raw: str):
    """Return (value or None, footnote list, ok flag)."""
    s = clean(raw)
    notes: list[str] = []
    while True:
        m = FOOTNOTE_RE.search(s)
        if not m:
            break
        notes = [n.strip() for n in m.group(1).split(",")] + notes
        s = s[: m.start()].strip()
    if NULL_RE.match(s) or s.lower() in {"na", "n/a", "--"}:
        return None, notes, True
    m = NUM_RE.match(s.replace(" ", ""))
    if not m:
        return None, notes, False
    return float(m.group(1).replace(",", "")), notes, True


def is_int_cell(text: str) -> int | None:
    s = clean(text)
    s = FOOTNOTE_RE.sub("", s).strip()
    s = s.rstrip("%_°").strip()
    m = re.fullmatch(r"(\d{1,3})\s*(?:%|°)?\s*(?:\([A-Za-z][^)]*\))?", s)  # e.g. "100 (Plug Up)"
    return int(m.group(1)) if m else None


@dataclass
class Column:
    idx: int
    header: str = ""
    role: str = "attr"          # attr | label | position | scalar | ignore
    position: float | None = None
    scalar_coeff: str | None = None


@dataclass
class ParsedTable:
    title: str
    position_basis: str
    columns: list[Column]
    records: list[dict] = field(default_factory=list)
    template_from: bool = False
    issues: list[str] = field(default_factory=list)


def find_position_row(cells: list[list[str]]) -> int | None:
    for ri, row in enumerate(cells[:8]):
        if ri and "RELATIVE FLOW" in " ".join(cells[ri - 1]).upper():
            decs = [parse_value(c)[0] for c in row if c]
            if len(decs) >= 4 and all(d is not None and d <= 1 for d in decs) and decs == sorted(decs):
                return ri
        nums = [is_int_cell(c) for c in row]
        vals = [n for n in nums if n is not None]
        prev = " ".join(cells[ri - 1]).lower() if ri else ""
        need = 2 if re.search(r"opening|rotation|travel|percent", prev) else 4
        if len(vals) >= need and vals == sorted(vals) and len(set(vals)) == len(vals) and max(vals) <= 100:
            # Must not be a data row: data rows have decimals somewhere.
            if not any(re.fullmatch(r"[\d,]*\.\d+", c) for c in row):
                return ri
    return None


def label_of(text: str) -> str | None:
    s = clean(text)
    s = FOOTNOTE_RE.sub("", s).strip()
    return LABEL_MAP.get(s.lower().replace(" ", ""))


def expand_rows(raw):
    """Clean cells; split rows whose number cells hold several stacked values
    (e.g. Fd table: "To open / To close" with "0.10 / 0.20")."""
    out, src = [], []
    for ri, row in enumerate(raw):
        parts = [[clean(x) for x in (c or "").split("\n") if clean(x)] for c in row]
        multi = [p for p in parts if len(p) > 1]
        k = len(multi[0]) if multi else 1
        numeric_multi = [p for p in multi if all(parse_value(x)[2] and parse_value(x)[0] is not None for x in p)]
        if k > 1 and len(numeric_multi) >= 2 and all(len(p) == k for p in numeric_multi):
            for j in range(k):
                out.append([p[j] if len(p) == k else (" ".join(p) if j == 0 else "") for p in parts])
                src.append(ri)
        else:
            out.append([clean(c) for c in row])
            src.append(ri)
    return out, src


def build_headers(cells: list[list[str]], n_header: int) -> list[str]:
    ncols = len(cells[0])
    rows = [list(r) for r in cells[:n_header]]
    # Title rows (one cell of text spanning the table) are not column headers.
    rows = [r if sum(1 for c in r if c) > 1 or r is rows[-1] else [""] * ncols for r in rows]
    # Spread a parent header rightwards over the sub-header cells it spans
    # (e.g. "Port Diameter" over "mm" | "Inches").
    for r in range(n_header - 1):
        for c in range(1, ncols):
            if not rows[r][c] and rows[r][c - 1]:
                below = rows[n_header - 1][c] if n_header - 1 > r else ""
                left_below = rows[n_header - 1][c - 1] if n_header - 1 > r else ""
                if below and is_int_cell(below) is None and left_below and is_int_cell(left_below) is None:
                    rows[r][c] = rows[r][c - 1]
    return [clean(" ".join(rows[r][c] for r in range(n_header) if rows[r][c])) for c in range(ncols)]


def gray_rects(page) -> list[tuple[float, float, float, float]]:
    out = []
    for r in page.rects:
        if not r.get("fill"):
            continue
        col = r.get("non_stroking_color")
        if isinstance(col, (list, tuple)):
            if len(col) == 1:
                g = col[0]
            elif len(col) == 3:
                g = sum(col) / 3 if max(col) - min(col) < 0.05 else None
            elif len(col) == 4:
                g = 1 - col[3] if col[0] == col[1] == col[2] == 0 else None
            else:
                g = None
        elif isinstance(col, (int, float)):
            g = col
        else:
            g = None
        if g is not None and 0.3 < g < 0.95:
            out.append((r["x0"], r["top"], r["x1"], r["bottom"]))
    return out


def shaded_fraction(bbox, rects) -> float:
    x0, t, x1, b = bbox
    area = max((x1 - x0) * (b - t), 1e-6)
    cov = 0.0
    for rx0, rt, rx1, rb in rects:
        w = min(x1, rx1) - max(x0, rx0)
        h = min(b, rb) - max(t, rt)
        if w > 0 and h > 0:
            cov += w * h
    return min(cov / area, 1.0)


def detect_basis(text: str) -> str:
    t = text.lower()
    if "relative flow" in t:
        return "relative_flow_coefficient"
    if "rotation" in t or "degree" in t or "disk angle" in t:
        return "deg_rotation"
    if "percent" in t or "% of" in t or "travel" in t or "opening" in t or "versus" in t:
        return "pct_travel"
    return "position"


def default_coeff(text: str) -> str:
    t = text
    if re.search(r"\bKv\b", t):
        return "Kv"
    return "Cv"


def parse_table(table, page, rects, template: "ParsedTable | None" = None) -> ParsedTable | None:
    raw = table.extract()
    if not raw or len(raw) < 2:
        return None
    cells, row_src = expand_rows(raw)
    # Drop columns that are empty in every row (layout artefacts); keep original indices for geometry.
    keep = [c for c in range(len(cells[0])) if any(row[c] for row in cells)]
    cells = [[row[c] for c in keep] for row in cells]
    ncols = len(cells[0])
    pos_row = find_position_row(cells)

    # Label column: the column holding the most coefficient labels.
    label_col, best = None, 0
    for c in range(ncols):
        n = sum(1 for row in cells if label_of(row[c]))
        if n > best:
            label_col, best = c, n
    if best < 2:
        label_col = None

    if pos_row is None and label_col is not None and template is not None and len(template.columns) == ncols \
            and template.columns[label_col].role == "label":
        # Continuation table printed without its header: reuse the previous table's columns.
        first = next(i for i, row in enumerate(cells) if label_of(row[label_col]))
        return fill_records(ParsedTable("", template.position_basis, template.columns, template_from=True),
                            cells, row_src, first, label_col, table, rects, " ".join(c.header for c in template.columns), keep)
    if pos_row is not None:
        n_header = pos_row + 1
    else:
        # No position axis: header ends at the first row whose later cells are mostly numeric.
        n_header = None
        for ri, row in enumerate(cells):
            vals = [parse_value(c) for c in row[1:] if c]
            if vals and sum(1 for v, _, ok in vals if ok and v is not None) >= max(1, len(vals) // 2) and ri > 0:
                n_header = ri
                break
        if n_header is None:
            return None

    headers = build_headers(cells, n_header)
    # Title rows: a header row with one cell of text and nothing else (e.g. "Quick Opening").
    title_bits = []
    for r in range(n_header):
        texts = [c for c in cells[r] if c]
        if 1 <= len(texts) <= 2 and r < n_header - 1 and not any(is_int_cell(t) is not None for t in texts):
            title_bits += [t for t in texts if len(t) > 2]
    header_text = " ".join(headers)
    basis = detect_basis(header_text) if pos_row is not None else "none"

    columns = [Column(i, headers[i]) for i in range(ncols)]
    pos_cols = []
    if pos_row is not None:
        for c in range(ncols):
            v = is_int_cell(cells[pos_row][c])
            if v is None and basis == "relative_flow_coefficient" and cells[pos_row][c]:
                v = parse_value(cells[pos_row][c])[0]
            if v is not None:
                columns[c].role = "position"
                columns[c].position = float(v)
                pos_cols.append(c)
    first_pos = min(pos_cols) if pos_cols else None
    if label_col is not None:
        columns[label_col].role = "label"

    for col in columns:
        if col.role != "attr":
            continue
        h = FOOTNOTE_RE.sub("", col.header).strip()
        for rx, name in SCALAR_HEADER_RE:
            if rx.search(h):
                col.role, col.scalar_coeff = "scalar", name
                break
        if col.role != "attr":
            continue
        if ATTR_WORDS.search(h) and not re.search(r"coef|percent|opening|rotation|throt|\bmin|\bcv\b|\bkv\b", h, re.I):
            continue  # attribute column, wherever it sits (e.g. V150 "Valve Size" after the label column)
        after_label = label_col is not None and col.idx > label_col
        after_pos = first_pos is not None and col.idx > first_pos
        if pos_row is None:
            if re.search(r"\bCL\s*\d+|\bclass\b|\bCv\b|\bKv\b|PN\s*\d+", h) and not ATTR_WORDS.search(re.sub(r"\bCL\s*\d+", "", h)):
                col.role, col.scalar_coeff = "scalar", default_coeff(header_text)
        elif after_label or after_pos:
            # Single-value column inside the value area, e.g. "Coeffs for 6 mm Travel".
            col.role = "scalar"
            col.scalar_coeff = None  # take the row's label
        if col.role == "attr" and not col.header and all(not row[col.idx] for row in cells[n_header:]):
            col.role = "ignore"

    pt = ParsedTable(" / ".join(title_bits), basis, columns)
    return fill_records(pt, cells, row_src, n_header, label_col, table, rects, header_text, keep)


def fill_records(pt, cells, row_src, n_header, label_col, table, rects, header_text, keep):
    columns, basis = pt.columns, pt.position_basis
    attr_cols = [c for c in columns if c.role == "attr"]
    value_cols = [c for c in columns if c.role in ("position", "scalar")]
    if not value_cols:
        return None

    current = {c.idx: "" for c in attr_cols}
    section = ""
    row_objs = table.rows
    config_seq = 0
    last_config_key = None
    prev_label = None
    for ri in range(n_header, len(cells)):
        row = cells[ri]
        texts = [c for c in row if c]
        if not texts:
            continue
        if re.match(r"^\d+\.\s+\S", row[0]) and len(texts) == 1:
            continue  # footnote row inside the table frame
        lab_cell = row[label_col] if label_col is not None else ""
        is_text_label = bool(TEXT_LABELS.get(lab_cell.lower().replace(" ", "")))
        vcells = [row[c.idx] for c in value_cols if row[c.idx]]
        numeric = [x for x in vcells if parse_value(x)[0] is not None]
        pos_cells = [(c, row[c.idx]) for c in value_cols if c.role == "position" and row[c.idx]]
        if pos_cells and all(is_int_cell(x) == c.position for c, x in pos_cells) and not label_of(lab_cell):
            continue  # header repeated inside the table (e.g. "10 20 ... 100")
        if not numeric and not is_text_label and not label_of(lab_cell):
            if not vcells:
                section = texts[0]  # title row for the rows below, e.g. "Two Stage"
            continue  # otherwise a repeated header row
        # Merged cells: carry attribute values down until a new value appears.
        new_attr = False
        for c in attr_cols:
            if row[c.idx]:
                if current[c.idx] != row[c.idx]:
                    new_attr = True
                current[c.idx] = row[c.idx]
        label = label_of(row[label_col]) if label_col is not None else None
        text_label = TEXT_LABELS.get(row[label_col].lower().replace(" ", "")) if label_col is not None else None
        if text_label:
            label = text_label
        if label_col is not None and not row[label_col] and prev_label and any(
                parse_value(row[c.idx])[0] is not None for c in value_cols if c.role == "position"):
            label = prev_label  # label cell merged over several rows (e.g. NotchFlo levels A/B/C)
        if label:
            prev_label = label
        if label_col is not None and not label and re.match(r"^flow coeffi", row[label_col], re.I):
            continue  # repeated header row
        if label_col is not None and not label and row[label_col]:
            pt.issues.append(f"unknown label {row[label_col]!r}")
            continue
        if label_col is not None and not label:
            continue
        # A configuration starts at a new attribute value, or at a Cv label in label layouts.
        starts = new_attr or (label in ("Cv", "Cvnet") ) or label_col is None
        key = (section, tuple(current[c.idx] for c in attr_cols))
        if starts or key != last_config_key:
            config_seq += 1
            last_config_key = key
        # Shading: average over this row's own value cells (the row bbox can include a size
        # cell merged over several rows, which would pick up shading from neighbouring rows).
        src = row_src[ri]
        vcells = [row_objs[src].cells[keep[c.idx]] for c in value_cols
                  if src < len(row_objs) and row_objs[src].cells[keep[c.idx]]]
        shaded = bool(vcells) and sum(shaded_fraction(vc, rects) for vc in vcells) / len(vcells) > 0.5
        for col in value_cols:
            raw_cell = row[col.idx]
            if not raw_cell:
                continue
            value, notes, ok = parse_value(raw_cell)
            if label in TEXT_LABELS.values():
                ok = True
            if not ok:
                pt.issues.append(f"unparsed {raw_cell!r} in column {col.header!r}")
            if col.role == "position":
                coeff = label or ("Fd" if basis == "relative_flow_coefficient" else default_coeff(header_text))
                position, pos_label = col.position, ""
            else:
                coeff = col.scalar_coeff or label or default_coeff(header_text)
                position, pos_label = None, col.header
            pt.records.append({
                "config_seq": config_seq,
                "section": section,
                "attrs": {c.header or f"col{c.idx}": current[c.idx] for c in attr_cols if current[c.idx]},
                "row_label": label or "",
                "coefficient": coeff,
                "position_basis": basis if col.role == "position" else "single",
                "position": position,
                "position_label": pos_label,
                "value": value,
                "value_raw": raw_cell,
                "footnotes": ",".join(notes),
                "shaded": shaded,
                "parse_ok": ok,
            })
    return pt


def page_title(page, top_limit: float) -> str:
    words = page.extract_words(keep_blank_chars=True, x_tolerance=2)
    lines: dict[int, list] = {}
    for w in words:
        if w["bottom"] <= top_limit:
            lines.setdefault(round(w["top"] / 3), []).append(w)
    out = []
    for k in sorted(lines):
        for w in sorted(lines[k], key=lambda w: w["x0"]):
            t = clean(w["text"])
            if not t or re.match(r"^(Catalog 12|Page\s|\w+ \d{4}|.*\d{4} - Page)", t):
                continue
            out.append(t)
    return " | ".join(out)


def legend_text(page, rects, tables) -> str:
    """Text next to small gray swatches outside the tables (e.g. 'Restricted trim')."""
    words = page.extract_words(keep_blank_chars=True, x_tolerance=2)
    out = []
    for x0, t, x1, b in rects:
        if x1 - x0 > 60 or b - t > 30:
            continue
        if any(tb[0] - 1 <= x0 and x1 <= tb[2] + 1 and tb[1] - 1 <= t and b <= tb[3] + 1 for tb in tables):
            continue
        near = [w for w in words if abs((w["top"] + w["bottom"]) / 2 - (t + b) / 2) < 6 and 0 <= w["x0"] - x1 < 30]
        if near:
            out.append(clean(" ".join(w["text"] for w in sorted(near, key=lambda w: w["x0"]))))
    return "; ".join(dict.fromkeys(out))


def keywords_in(text: str, options: list[str]) -> list[str]:
    """Options found in text; a longer option hides the shorter ones it contains."""
    t, found = text.lower(), []
    for o in sorted(options, key=len, reverse=True):
        if o.lower() in t:
            found.append(o)
            t = t.replace(o.lower(), " ")
    return found


def find_keyword(text: str, options: list[str]) -> str:
    found = keywords_in(text, options)
    return found[0] if found else ""


CHAR_CODES = {"mod =%": "Modified Equal Percentage", "=%": "Equal Percentage", "lin": "Linear",
              "linear": "Linear", "qo": "Quick Opening", "quick open": "Quick Opening"}


def char_from_attrs(attrs: dict) -> str:
    for k, v in attrs.items():
        if re.search(r"char", k, re.I):
            code = v.lower().split("/")[-1].strip()
            for c, name in CHAR_CODES.items():
                if code.endswith(c):
                    return name
    return ""


def page_notes(page) -> list[tuple[str, str]]:
    """Numbered footnotes and 'Note:' lines printed on the page."""
    out = []
    for line in (page.extract_text() or "").splitlines():
        line = clean(line)
        m = re.match(r"^(\d{1,2})\.\s+(\S.*)$", line)
        if m and not re.match(r"^[\d.\s-]+$", m.group(2)):
            out.append((m.group(1), m.group(2)))
        elif re.match(r"^Notes?:", line):
            out.append(("note", re.sub(r"^Notes?:\s*", "", line)))
    return out


CONFIG_FIELDS = ["config_id", "page", "printed_label", "family", "table_no", "page_title", "table_title",
                 "section", "characteristic", "flow_direction", "nps", "attrs", "restricted_trim", "restricted_source"]
VALUE_FIELDS = ["config_id", "coefficient", "position_basis", "position", "position_label",
                "value", "value_raw", "footnotes", "parse_ok"]


def main(pdf_path: str, inventory_path: str, out_dir: str, report_path: str | None = None) -> None:
    inv = [r for r in csv.DictReader(open(inventory_path, encoding="utf-8"))
           if r["section"].startswith("1 ") and r["page_kind"] not in ("blank", "redirect")]
    pdf = pdfplumber.open(pdf_path)
    configs: dict[str, dict] = {}
    values: list[dict] = []
    notes: list[dict] = []
    report = []
    templates: dict[str, ParsedTable] = {}
    for r in inv:
        pn = int(r["pdf_page"])
        page = pdf.pages[pn - 1]
        rects = gray_rects(page)
        tables = page.find_tables(TABLE_SETTINGS)
        parsed = []
        for t in tables:
            pt = parse_table(t, page, rects, templates.get(r["valve_family"]))
            if pt and pt.records:
                parsed.append((t, pt))
                if not pt.template_from:
                    templates[r["valve_family"]] = pt
        top = min((t.bbox[1] for t, _ in parsed), default=page.height)
        ptitle = page_title(page, top)
        page_text = clean(page.extract_text() or "")
        page_chars = keywords_in(page_text, CHARACTERISTICS)
        page_flows = keywords_in(page_text, FLOW_DIRECTIONS)
        legend = legend_text(page, rects, [t.bbox for t, _ in parsed])
        pnotes = page_notes(page) if parsed else []
        notes += [{"page": pn, "printed_label": r["printed_label"], "note": k, "text": v} for k, v in pnotes]
        # Restricted trim is marked either by gray shading or by a footnote such as "4. Restricted trim."
        restricted_notes = [k for k, v in pnotes if k.isdigit() and re.match(r"restricted trim", v, re.I)]
        shading_meaning = "Restricted trim" if re.search(r"restricted trim", page_text, re.I) else legend
        n, issues = 0, []
        for ti, (t, pt) in enumerate(parsed, 1):
            issues += pt.issues
            for rec in pt.records:
                cid = f"{pn}-{ti}-{rec['config_seq']}"
                if cid not in configs:
                    ctx = " ".join([ptitle, pt.title, rec["section"], " ".join(rec["attrs"].values())])
                    configs[cid] = {
                        "config_id": cid, "page": pn, "printed_label": r["printed_label"],
                        "family": r["valve_family"], "table_no": ti, "page_title": ptitle,
                        "table_title": pt.title, "section": rec["section"],
                        "characteristic": (find_keyword(" ".join([rec["section"], pt.title]), CHARACTERISTICS)
                                           or char_from_attrs(rec["attrs"]) or find_keyword(ctx, CHARACTERISTICS)
                                           or (page_chars[0] if len(page_chars) == 1 else "")),
                        "flow_direction": (find_keyword(ctx, FLOW_DIRECTIONS)
                                           or (page_flows[0] if len(page_flows) == 1 else "")),
                        "nps": next((v for k, v in rec["attrs"].items() if re.search(r"size|nps|\bdn\b", k, re.I)), ""),
                        "attrs": json.dumps(rec["attrs"], ensure_ascii=False),
                        "restricted_trim": 0, "restricted_source": "",
                    }
                    for k in restricted_notes:
                        if any(re.search(rf"\({k}\)", v) for v in rec["attrs"].values()):
                            configs[cid]["restricted_trim"] = 1
                            configs[cid]["restricted_source"] = f"footnote {k}"
                if rec["shaded"] and rec["coefficient"] in ("Cv", "Cvnet") and not configs[cid]["restricted_trim"]:
                    configs[cid]["restricted_trim"] = 1
                    configs[cid]["restricted_source"] = f"shaded row ({shading_meaning or 'no legend on page'})"
                values.append({
                    "config_id": cid, "coefficient": rec["coefficient"],
                    "position_basis": rec["position_basis"],
                    "position": "" if rec["position"] is None else f"{rec['position']:g}",
                    "position_label": rec["position_label"],
                    "value": "" if rec["value"] is None else f"{rec['value']:g}",
                    "value_raw": rec["value_raw"], "footnotes": rec["footnotes"],
                    "parse_ok": int(rec["parse_ok"]),
                })
                n += 1
        report.append({"page": pn, "label": r["printed_label"], "tables_found": len(tables),
                       "tables_parsed": len(parsed), "records": n, "issues": issues})
    for name, fields, rows in (("configs.csv", CONFIG_FIELDS, configs.values()),
                               ("coefficients.csv", VALUE_FIELDS, values),
                               ("page_notes.csv", ["page", "printed_label", "note", "text"], notes)):
        with open(f"{out_dir}/{name}", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
    if report_path:
        json.dump(report, open(report_path, "w"), indent=1)
    empty = [f"{x['page']}:{x['label']}" for x in report if x["records"] == 0]
    print(f"pages {len(report)}, configs {len(configs)}, values {len(values)}, pages with no tables {len(empty)}")
    if empty:
        print("  ", " ".join(empty))


if __name__ == "__main__":
    main(*sys.argv[1:])
