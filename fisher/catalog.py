"""Deterministic lookups over the extracted Fisher Catalog 12 coefficient data.

Everything here reads the frozen CSVs in data/ and does plain arithmetic:
the same question always gives the same answer, and every answer carries the
catalog page it came from.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


# ---------------------------------------------------------------- sizes

def _size_to_float(s: str) -> float | None:
    s = s.strip()
    m = re.fullmatch(r"(\d+)-(\d+)/(\d+)", s)
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    m = re.fullmatch(r"(\d+)/(\d+)", s)
    if m:
        return int(m.group(1)) / int(m.group(2))
    m = re.fullmatch(r"\d+(?:\.\d+)?", s)
    return float(s) if m else None


# Nominal metric size (DN, mm) to NPS (inches), for tables that print DN.
DN_TO_NPS = {15: 0.5, 20: 0.75, 25: 1, 32: 1.25, 40: 1.5, 50: 2, 65: 2.5, 80: 3, 100: 4, 125: 5, 150: 6,
             200: 8, 250: 10, 300: 12, 350: 14, 400: 16, 450: 18, 500: 20, 600: 24, 750: 30, 900: 36}


def parse_nps(raw: str, dn: bool = False) -> list[float]:
    """Body sizes (NPS, inches) named in a catalog size cell.

    "1-1/2(2)" -> [1.5]; "2 & 3 x 2" -> [2.0, 3.0]; "DN25 / NPS 1" -> [1.0];
    "6.35 (1/4) 12.7 (1/2)" -> [0.25, 0.5]; "20x16" -> [20.0]; "1 & 1-1/4" -> [1.0, 1.25].
    With dn=True (the column is labelled DN), "80" -> [3.0].
    """
    if not raw:
        return []
    if dn and not re.search(r"\bNPS\b", raw, re.I):
        return [float(DN_TO_NPS[int(v)]) for v in re.findall(r"\d+", re.sub(r"\(\d+\)", "", raw))
                if int(v) in DN_TO_NPS]
    s = re.sub(r"\((\d+)\)", "", raw)          # footnote markers
    s = s.replace("‐", "-").replace("X", "x")
    paren = re.findall(r"\((\d+-\d+/\d+|\d+/\d+|\d+)\)", s)
    if paren:                                   # metric with inches in brackets
        return [v for v in (_size_to_float(p) for p in paren) if v is not None]
    if re.search(r"\bNPS\b", s, re.I):
        s = re.split(r"\bNPS\b", s, flags=re.I)[-1]
    out = []
    for part in re.split(r",|&|\band\b", s):
        m = re.match(r"\s*(\d+-\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)", part)
        if m:
            v = _size_to_float(m.group(1))
            if v is not None and v not in out:
                out.append(v)
    return out


# ---------------------------------------------------------------- data model

@dataclass
class Config:
    """One valve configuration: one block of a catalog table."""
    config_id: str
    page: int
    printed_label: str
    family: str
    page_title: str
    table_title: str
    section: str
    characteristic: str
    flow_direction: str
    nps: str
    sizes: list[float]
    attrs: dict[str, str]
    restricted: bool
    restricted_source: str
    curves: dict[str, dict[float, float]] = field(default_factory=dict)
    position_basis: str = ""
    singles: dict[tuple[str, str], float] = field(default_factory=dict)
    raw: dict[tuple[str, str], str] = field(default_factory=dict)
    footnotes: dict[tuple[str, str], str] = field(default_factory=dict)
    flags: list[dict] = field(default_factory=list)

    @property
    def source(self) -> str:
        return f"Fisher Catalog 12, page {self.printed_label} (PDF page {self.page})"

    def curve(self, coefficient: str = "Cv") -> list[tuple[float, float]]:
        """(opening, value) points for a coefficient, in order of opening."""
        return sorted(self.curves.get(coefficient, {}).items())

    def rated(self, coefficient: str = "Cv") -> float | None:
        """Value at full opening (largest position listed)."""
        pts = self.curve(coefficient)
        return pts[-1][1] if pts else None

    def value_at(self, opening: float, coefficient: str = "Cv") -> float | None:
        """Linear interpolation between catalog points. None outside the listed range."""
        pts = self.curve(coefficient)
        if not pts or opening < pts[0][0] or opening > pts[-1][0]:
            return None
        for (p0, v0), (p1, v1) in zip(pts, pts[1:]):
            if p0 <= opening <= p1:
                return v0 if p1 == p0 else v0 + (v1 - v0) * (opening - p0) / (p1 - p0)
        return pts[-1][1] if opening == pts[-1][0] else None

    def opening_for(self, value: float, coefficient: str = "Cv") -> float | None:
        """Smallest opening at which the interpolated curve reaches `value`. None if never reached."""
        pts = self.curve(coefficient)
        if not pts:
            return None
        if pts[0][1] >= value:
            return pts[0][0]
        for (p0, v0), (p1, v1) in zip(pts, pts[1:]):
            if v0 < value <= v1:
                return p0 + (p1 - p0) * (value - v0) / (v1 - v0)
        return None

    def to_dict(self) -> dict:
        return {
            "config_id": self.config_id, "family": self.family, "source": self.source,
            "title": " | ".join(x for x in (self.page_title, self.table_title, self.section) if x),
            "characteristic": self.characteristic, "flow_direction": self.flow_direction,
            "nps": self.nps, "attributes": self.attrs, "restricted_trim": self.restricted, "restricted_source": self.restricted_source,
            "position_basis": self.position_basis,
            "curves": {k: {f"{p:g}": v for p, v in sorted(c.items())} for k, c in self.curves.items()},
            "single_values": {f"{k} [{lbl}]": v for (k, lbl), v in self.singles.items()},
            "flags": self.flags,
        }


@dataclass
class Alias:
    valve: str
    uses: str
    pages: list[int]
    condition: str
    source_label: str
    source_text: str


def _rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class Catalog:
    def __init__(self, configs: dict[str, Config], aliases: list[Alias], notes: dict[int, list[tuple[str, str]]]):
        self.configs = configs
        self.aliases = aliases
        self._notes = notes

    @classmethod
    @lru_cache(maxsize=4)
    def load(cls, data_dir: str | Path | None = None) -> "Catalog":
        d = Path(data_dir) if data_dir else DATA_DIR
        configs: dict[str, Config] = {}
        for r in _rows(d / "configs.csv"):
            attrs = json.loads(r["attrs"])
            size_key = next((k for k, v in attrs.items() if v == r["nps"] and re.search(r"size|nps|\bdn\b", k, re.I)), "")
            dn = bool(re.search(r"\bDN\b", size_key)) and not re.search(r"\bNPS\b", size_key)
            configs[r["config_id"]] = Config(
                config_id=r["config_id"], page=int(r["page"]), printed_label=r["printed_label"],
                family=r["family"], page_title=r["page_title"], table_title=r["table_title"],
                section=r["section"], characteristic=r["characteristic"], flow_direction=r["flow_direction"],
                nps=r["nps"], sizes=parse_nps(r["nps"], dn=dn), attrs=attrs,
                restricted=r["restricted_trim"] == "1", restricted_source=r["restricted_source"],
            )
        for v in _rows(d / "coefficients.csv"):
            c = configs[v["config_id"]]
            key = (v["coefficient"], v["position"] or v["position_label"])
            c.raw[key] = v["value_raw"]
            if v["footnotes"]:
                c.footnotes[key] = v["footnotes"]
            if v["value"] == "":
                continue
            if v["position"] != "":
                c.curves.setdefault(v["coefficient"], {})[float(v["position"])] = float(v["value"])
                c.position_basis = v["position_basis"]
            else:
                c.singles[(v["coefficient"], v["position_label"])] = float(v["value"])
        flags_path = d / "flags.csv"
        if flags_path.exists():
            for f in _rows(flags_path):
                if f["config_id"] in configs:
                    configs[f["config_id"]].flags.append(
                        {k: f[k] for k in ("coefficient", "position", "check", "severity", "detail")})
        aliases = [Alias(a["valve"], a["uses"], [int(p) for p in a["pages"].split(";") if p],
                         a["condition"], a["source_label"], a["source_text"])
                   for a in _rows(d / "aliases.csv")]
        notes: dict[int, list[tuple[str, str]]] = {}
        for n in _rows(d / "page_notes.csv"):
            notes.setdefault(int(n["page"]), []).append((n["note"], n["text"]))
        return cls(configs, aliases, notes)

    # ------------------------------------------------------------ queries

    def families(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.configs.values():
            out[c.family] = out.get(c.family, 0) + 1
        return dict(sorted(out.items()))

    def get(self, config_id: str) -> Config:
        return self.configs[config_id]

    def notes(self, page: int) -> list[tuple[str, str]]:
        """Footnotes printed on a catalog page (number, text)."""
        return self._notes.get(page, [])

    def resolve(self, valve: str) -> list[Alias]:
        """Catalog statements that a valve uses another valve's coefficients."""
        v = valve.strip().upper()
        return [a for a in self.aliases if a.valve.upper() == v]

    def find(self, family: str | None = None, nps: float | str | None = None,
             characteristic: str | None = None, flow_direction: str | None = None,
             text: str | None = None, include_restricted: bool = True,
             coefficient: str | None = "Cv", include_aliases: bool = True) -> list[Config]:
        """Filter configurations.

        `family` may also be a valve the catalog says uses another valve's coefficients
        (e.g. "EDR" -> ED pages); with include_aliases those tables are included too.
        """
        allowed: list[tuple[str, set[int] | None]] | None = None
        if family:
            allowed = [(family.upper(), None)]
            if include_aliases:
                allowed += [(a.uses.upper(), set(a.pages) or None)
                            for a in self.resolve(family) if a.uses != "external"]
        size = _size_to_float(str(nps)) if nps is not None else None
        out = []
        for c in self.configs.values():
            if allowed is not None and not any(
                    c.family.upper() == fam and (pages is None or c.page in pages) for fam, pages in allowed):
                continue
            if size is not None and size not in c.sizes:
                continue
            if characteristic and characteristic.lower() not in c.characteristic.lower():
                continue
            if flow_direction and flow_direction.lower() not in c.flow_direction.lower():
                continue
            if text:
                blob = " ".join([c.page_title, c.table_title, c.section, json.dumps(c.attrs)]).lower()
                if text.lower() not in blob:
                    continue
            if not include_restricted and c.restricted:
                continue
            if coefficient and coefficient not in c.curves and not any(k == coefficient for k, _ in c.singles):
                continue
            out.append(c)
        return sorted(out, key=lambda c: (c.page, [int(x) for x in c.config_id.split("-")]))

    def find_valves(self, required_cv: float, min_open: float = 20, max_open: float = 80,
                    **filters) -> list[tuple[Config, float]]:
        """Configurations that pass `required_cv` between `min_open` and `max_open` (% travel or degrees).

        Returns (config, opening) sorted by smallest body size, then by opening.
        """
        hits = []
        for c in self.find(coefficient="Cv", **filters):
            op = c.opening_for(required_cv)
            if op is not None and min_open <= op <= max_open:
                hits.append((c, round(op, 1)))
        return sorted(hits, key=lambda h: (min(h[0].sizes) if h[0].sizes else 1e9, h[1], h[0].config_id))
