# Fisher Catalogs 12 and 14: deterministic lookup and sizing tools

Data and tools built from Emerson's **Fisher Catalog 12, ASME/ISA/IEC Valve Sizing** (D103182X012, April 2022 edition) and **Fisher Catalog 14, Actuator Sizing** (D103428X012). Catalog 14 is covered in [its own section below](#catalog-14-actuator-sizing).

## The unified dataset

**`data/fisher.db`** (SQLite) holds both catalogs in one schema. It is built from the same checked files the tools use, and tests check that the two agree. The purpose is a single, contextualized dataset that deterministic engineering tools can rely on:

- **One set of keys and units.** Configurations, sizes (NPS, inches), ports and travels (inches), angles (degrees) and pressure drops (psi unless a `unit` column says otherwise).
- **Context on every record.** Valve family, characteristic, flow direction, actuator, size, supply, bench set, spring, leakage class, action, balanced or unbalanced construction.
- **Provenance on every row.** Catalog, PDF page and printed page label. Each extracted value also records whether a second PDF reader confirmed it.
- **Joined.** `valve_actuator_link` connects Catalog 12 valve configurations to the Catalog 14 actuator ratings that apply. `valve_actuator_coverage` says why a configuration has none.
- **Errors kept, not hidden.** Catalog mistakes are flagged in `catalog_flag`. Chart-derived values are labelled approximate.

**[`docs/DATA_MODEL.md`](docs/DATA_MODEL.md)** describes every table and column. It is generated from the same schema definition as the database, and a test checks that they match.

```bash
python3 -m fisher sql "SELECT actuator, actuator_size, supply, max_dp, actuator_page FROM v_valve_actuator WHERE config_id = '152-1-8' AND unit = 'psi' AND max_dp >= 300"
```

```python
from fisher import db
rows = db.query("SELECT * FROM v_cv_curve WHERE family = ? AND nps_text = ?", ("ED", "3"))
```

Any SQLite client (Python, Excel via ODBC, DBeaver, Power BI) can open the file directly. In the UI, "Query the dataset" runs read-only SQL.

- **Lookups:** find a valve configuration and read its Cv, Kv, XT, FL and Fd at any opening.
- **Valve selection:** list configurations that reach a required Cv between, say, 20% and 80% open.
- **Sizing:** the Section 2 ISA/IEC liquid and gas equations as plain functions, plus flow and pressure-drop prediction, velocity, and liquid-gas mixtures.
- **Sizing on a specific valve:** repeats the catalog's hand iteration (size, find the opening, re-read xT or FL there, resize) until the opening settles.
- **Reference data:** saturated steam, gas k values, pipe and valve flow areas, leakage classes, unit conversions (Section 2).
- **Noise:** the Section 3 hydrodynamic (liquid) noise prediction.

There is no AI at run time. The tools read frozen CSV files and do arithmetic, so the same question always gives the same answer, and every answer names the catalog page it came from.

## What was extracted

| | |
|---|---|
| Coefficient pages read | 300 of 302 table pages in Section 1 (the 2 others are text and figures only) |
| Valve families | All 64: 60 have tables (plus the Fd reference table on page 1-1). EDR and V300 use other valves' tables, FB points to a separate Emerson document (`aliases.csv`), and Three-Way Butterfly is guidance and figures only |
| Configurations | 3,593 (one block of a table: valve, size, port, trim, characteristic, flow direction) |
| Values | 92,949 (Cv 33.5k, Kv 20.8k, XT 18.0k, FL 9.8k, Fd 8.5k, and others) |
| Restricted trim | 107 configurations, marked by gray shading or a "Restricted trim" footnote |

## How it was checked

1. **Second reader.** Every row of values was re-read with a different PDF engine (poppler `pdftotext`) and had to appear on the page in the same order. 8,592 of 8,596 rows matched exactly. The other 4 were checked by eye and are correct: poppler wraps two of them across lines, and two have a stray glyph next to a number.
   The 34 reference tables got the same check. Every row matched except three cases checked another way: the temperature-conversion table (all 134 °F/°C pairs verified by formula), a table of formulas, and one EH flow-area row whose label wraps over three lines.
2. **Physics checks** (`data/flags.csv`): Kv ≈ 0.865 × Cv for 20,000 pairs, XT/FL/Fd in range, and Cv rising with opening.
3. **The catalog's own worked examples.** All Section 2 sample problems are tests and reproduce the printed answers. The data tests check that lookups return the exact table values those examples quote (e.g. "NPS 3 CL300 ED linear cage has a Cv of 133 at 80 percent travel").
4. **Hand check.** 20 tables were compared against the PDF by hand, with no errors found.

The remaining warnings (243 values on 39 pages) are **errors or quirks in the catalog itself**. They are flagged, never corrected. Examples:

- A11-6 prints a Cv of 178 as "078".
- HP-49 prints every Kv as 0.00.
- CV500-3 labels a row "Kv" that holds values of about 0.2–0.45.
- EZ-1 prints "14.7" in the XT 6 mm travel column, copied from Cv.
- 5 cells can't be read as numbers ("0..696", "0.6.6", ".9.").
- Liquid sample problem 3 prints N4 = 7600, but Table 2 says 76000, and only 76000 reproduces its printed answer.

Any configuration's warnings are returned with it (`flags`).

## Exact vs approximate

Everything comes from printed numbers or equations **except four noise terms and the two liquid-gas mixture factors**, which the catalog gives only as charts. Those charts were digitized from the page images (`extract/digitize_charts.py`). Results are marked approximate in the code and refuse inputs outside each chart's range.

| Chart | Digitized as | Accuracy | Check against the catalog's own reading |
|---|---|---|---|
| SPL_ΔP (page 3-8) | two straight lines on log ΔP | ±0.3 dB scatter | cavitating 107.0 vs 107; non-cavitating 79.9 vs 81 (the example reads ~1 dB high) |
| ΔSPL_Cv (3-9) | straight line on log Cv | ±0.4 dB | 18.1 vs 18 |
| ΔSPL_Km (3-10) | straight line on log Km | ±0.1 dB | 0.8 vs 0.7 |
| ΔSPL_G (3-11) | straight line on log G (0.3–3) | ±0.1 dB | 0 vs 0 |
| Fm (2-30, fig. 1) | 50 sampled points | about ±0.02 | 0.458 vs 0.475; 0.968 vs 0.97 |
| Critical ΔP/P1 (2-30, fig. 2) | 31 sampled points | about ±0.01 | 0.40 vs 0.40 |

The page 3-7 noise example comes out at 84.2 dBA against the printed 84.1. ΔSPL_Ar uses the page 3-1 equation (by valve style), not the older page 3-10 chart. The two agree within about 1 dB for Ar ≥ 0.35 at most Km values, including the example, but differ by up to 18 dB at low Ar with high Km.

## Use

### In a browser

```bash
python3 -m fisher.ui
```

Then open http://127.0.0.1:8000. One page with a form for each tool: find valves, select by required Cv, valve details (coefficient table, Cv curve, footnotes, flags), liquid and gas sizing, sizing on a catalog valve, flow prediction, saturated steam, and noise. The "Catalog example" button fills in a worked example from the catalog. Standard library only; the page runs the same code as the command line.

### From an AI assistant (MCP)

```bash
claude mcp add fisher -- python3 -m fisher.mcp_server
```

Run that in this folder. `fisher.mcp_server` speaks the Model Context Protocol over stdio (standard library only) and offers every command below as a tool, with input schemas generated from the command-line parser, plus `sql` over the whole dataset.

### From the command line

```bash
python3 -m fisher find --family ED --nps 3 --characteristic linear
```

```bash
python3 -m fisher show 122-1-8
```

```bash
python3 -m fisher select --cv 120 --family ES --no-restricted
```

```bash
python3 -m fisher liquid --q 2200 --p1 389.7 --p2 114.7 --gf 0.93 --fl 0.84 --pv 41.9 --ff 0.90
```

```bash
python3 -m fisher gas --q 6e6 --gg 0.6 --t1 520 --p1 214.7 --p2 64.7 --k 1.31 --xt 0.137
```

```bash
python3 -m fisher size-valve 309-1-3 --q 6e6 --gg 0.6 --t1 520 --p1 214.7 --p2 64.7 --k 1.31
```

```bash
python3 -m fisher noise --dp 175 --p1 250 --pv 11.5 --cv 70 --km 0.7 --nps 4 --schedule 40
```

```bash
python3 -m fisher steam --psia 40
```

```python
from fisher import Catalog
from fisher import sizing

cat = Catalog.load()
valve = cat.find(family="ES", nps=4, characteristic="Equal Percentage", include_restricted=False)[0]
fp = sizing.fp(valve.rated(), 4, sizing.sum_k(4, D_in=8, D_out=8))
need = sizing.liquid_cv(800, 314.7, 289.7, 0.50, fp_value=fp).cv
print(valve.source, need, valve.opening_for(need))   # page ES-5, Cv 121.5 needed, 74% open
```

Behavior worth knowing:

- Values between catalog points are **linearly interpolated** by default; `interp="pchip"` uses a monotone cubic, which `docs/INTERPOLATION.md` shows is about twice as accurate on the catalog's own curves. Outside the listed openings the result is `None`, never extrapolated.
- Catalog errors (Kv/Cv mismatches, typos such as "078" or "0..696") are corrected by default from the catalog's own evidence, with a confidence level; `Catalog.load(corrections=False)` gives every value as printed. See `docs/CORRECTIONS.md`.
- `find(family="EDR")` follows the catalog's "identical to" and "also appropriate for" statements. Pass `include_aliases=False` to turn that off.
- Characteristic is blank for 679 configurations and flow direction for 408, because the catalog doesn't state them for those tables (mostly butterfly and ball valves). They are left blank, not guessed.
- The Reynolds-number factor FR comes from Table 3 by linear interpolation, which the catalog says is satisfactory.

## Catalog 14: actuator sizing

| Section | Pages | What is extracted | Use |
|---|---|---|---|
| A, sliding-stem, pressure drop method | 1–34 | 2,559 maximum allowable shutoff ΔP values (585C, 657, 667) by port, travel, yoke boss, actuator size, air pressure or bench set | `actuators.sliding_stem()`, `actuator-sliding` |
| C, rotary, pressure drop method | 175–364 | 19,082 maximum allowable ΔP values (1052, 1061, 2052, FieldQ on 8510, 8532, 8580, 9500, A11, CV500, Control-Disk, V150, V200, V300, V500) by valve size or shaft, opening angle, actuator size, supply pressure and spring | `actuators.rotary()`, `actuator-rotary` |
| B, sliding-stem, force method | 35–174 | Every table typed (`c14_table_value`): port and unbalance areas, seat loads, packing friction, actuator forces and springs (585C, 657, 657C, 657R, 667, 685, 685SE/SR, 785C, 3025), stem loads, piston ring friction charts | `fisher.force`, `fisher.actuator_force`, `fisher.piston_actuators`, `fisher.stem_load` |
| D, rotary, torque method | 365–560 | Every table typed: A, B, C, K, MAST, shaft strength for 26 valves (`torque_factor`); 1051, 1052, 1061, 1068, 2052 output torque (`actuator_torque`) | `fisher.torque`, `fisher.rotary_actuator`, `valve-torque`, `rotary-actuator` |

- **ΔP values:** each of the 21,641 values was confirmed by the second PDF reader. That row's values appear, in order, on one line of poppler's text.
- **Other tables:** all 695 tables are kept as printed in `data/catalog14/tables/`, with an index giving page, heading and how many rows the second reader confirms.
- **Sections B and D:** 35,000 values typed with row keys and column paths; all confirmed by the second reader (126 only as "found on the page", see `docs/GAPS.md`).

```bash
python3 -m fisher actuator-sliding --dp 500 --port 2.5 --actuator 585C
```

### Force and torque methods

- **Force method (sliding-stem, section B):** `fisher.force` calculates the valve body force A + B + C + D. A is static unbalance (eight cases on pages B-2/B-3); B is seat load from the Table 4 rules and Table 5 factors; C is packing friction (Tables 6–6D); D is additional forces, supplied by you. `fisher.actuator_force` then selects a 585C (springless) or a 657, 657R or 667 spring-and-diaphragm actuator, either from the available-force tables or by the spring-rate calculation. The tests reproduce the catalog's sample calculations on pages B-77, B-80.1, B-80.3 and B-81.
- **More sliding-stem actuators:** `fisher.piston_actuators` sizes the 585C spring-biased (B-19), 685 (B-26), 685SE/685SR with the catalog's equations (B-27.1), 785C (B-27.8) and 3025 (B-73); 657C joins the diaphragm tables. `fisher.stem_load` checks the actuator force against the maximum allowable stem load (B-99; reproduces its worked example). `force.piston_ring_friction` reads figures 4 and 4A.
- **Torque method (rotary, section D):** `fisher.torque` calculates breakout torque TB = A·ΔPshutoff + B and dynamic torque TD = C·ΔPeff (liquid ΔPeff = FL²(P1abs − FF·Pv), gas K·P1abs) for every valve with typed factors, and checks them against the shaft limit. `fisher.rotary_actuator` then picks the 1051, 1052, 1061, 1068 or 2052 configurations that cover the valve at every angle. The tests reproduce the examples on pages D-100 and D-113/D-114.

```bash
python3 -m fisher rotary-actuator --valve CV500 --nps 4 --dp-shutoff 150 --p1 150 --fl 0.6 --ff 0.94 --pv 0.5 --flow forward
```

```bash
python3 -m fisher stem-load --stem 0.75 --temp-f 400 --force 9000 --design ED
```

What isn't covered yet is listed in `docs/GAPS.md` (item 1).

### Linked to the Catalog 12 valve configurations

Each Catalog 12 configuration id (e.g. `152-1-8`) links to the Catalog 14 ratings for that valve:

- **Sliding-stem:** matched on the port diameter and travel that Catalog 12 prints for the configuration, and on balanced or unbalanced construction from Catalog 14's own list on page A-2. Balanced: ED, EWD, ET, EWT. Unbalanced: D, ES, EWS, EZ. Rows Catalog 14 marks for one valve, e.g. "(ET, Class V Leakage)", only match that valve.
- **Rotary:** matched on valve family and NPS, plus the opening angle if you give one.

Of the 959 configurations in valve families that Catalog 14's pressure drop tables cover, 470 link to ratings. The rest are sizes, ports or travels Catalog 14 doesn't list (mostly ports of 14.75 inches and up). Every configuration's result is in `data/links/catalog12_to_catalog14.csv`, with a note explaining any that don't link.

```bash
python3 -m fisher actuators-for 152-1-8 --dp 300
```

In the UI, "Actuators for a valve" does the same, and every Valve details page links to it.

Two fixes came out of this. Catalog 12 tables that print DN sizes (8580, Control-Disk, V200U, 84000, 89000) are now converted to NPS. Fractional dimensions such as a "1/4" inch port are now read as fractions.

```bash
python3 -m fisher actuator-rotary --dp 200 --valve V150 --nps 4 --angle 0
```

## Files

| Path | Contents |
|---|---|
| `data/configs.csv` | One row per configuration: page, family, titles, size, attributes (JSON), restricted trim |
| `data/coefficients.csv` | One row per value: coefficient, opening (% travel, degrees, or a single value), value, printed text, footnotes |
| `data/page_notes.csv` | Footnotes printed on each page (what the `(n)` markers mean) |
| `data/aliases.csv` | Valves the catalog says use another valve's coefficients |
| `data/flags.csv` | Validation warnings |
| `data/crosscheck.csv` | Second-reader result for every value row |
| `data/reference/` | Section 2 and 3 reference tables as printed (`tables/`, `index.csv`), saturated steam, leakage classes, chart digitizations |
| `data/fisher.db` | **The unified dataset** (SQLite); schema and column meanings in `docs/DATA_MODEL.md` |
| `docs/GAPS.md` | Gaps, limits, assumptions and open questions |
| `data/links/` | `catalog12_to_catalog14.csv`: every Catalog 12 configuration with its Catalog 14 match |
| `data/catalog14/` | Catalog 14: `allowable_dp.csv` (sections A and C, one row per value) with `pages.csv` (page headings), every table as printed (`tables/`, `index.csv`) |
| `fisher/` | `actuators.py` Catalog 14 actuator selection, `catalog.py` lookups, `sizing.py` equations, `select.py` sizing on a catalog valve, `reference.py` reference data, `noise.py` noise; standard library only |
| `extract/` | Extraction, validation, cross-check and chart digitizing scripts |
| `docs/page_inventory.csv` | Every PDF page with its printed label, family and type |

## Rebuild

The PDF isn't stored in the repo (it is Emerson's copyrighted document).

```bash
pip install -r requirements.txt
```

```bash
make data
```

```bash
make test
```

`make data` downloads the PDF and checks its SHA-256 hash. If Emerson publishes a new edition, the check fails, so you know to review the flags and cross-check before trusting new output.

Not covered: the Fisher Sizing Program pages (2-17 to 2-22: FSP vapor pressure and pulp stock, which describe software rather than give data), the general sound-characteristics pages in Section 3 (3-2 to 3-6), and the superheated steam density chart (2-35).
