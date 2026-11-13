# Gaps and unknowns

The state of the unified dataset (`data/fisher.db`) and tools, updated after adding the force and torque methods and typing sections B and D. Numbers come from the current data. Each item says why it matters and what would close it.

## Most important first

| # | Gap | Why it matters | To close it |
|---|---|---|---|
| 1 | **Force and torque methods are only partly implemented.** Done: valve body forces A + B + C + D; 585C springless and 657/657R/667 actuator selection; torque equations; 7600 butterfly torque data (all tested against the catalog's sample calculations). Not done: 585C spring-biased, 685/685SE/685SR, 785C, 3025, 657C actuator tables; stem load check (B-99); piston-ring friction charts (figures 4/4A); typed torque data for valves other than the 7600; actuator torque output tables (1051, 1052, 1061, 1066, 2052, Bettis) | Rotary valves still need an actuator answer outside the pressure drop tables | Extract the remaining actuator tables and per-valve torque tables page by page, as done for the 7600 and 657 |
| 2 | **No engineer has validated results against Fisher's own software** (Fisher Specification Manager / FIRST) | The tests reproduce the catalogs' own worked examples, which is not the same as matching the current product software | Run 10–20 real sizing cases through both and compare |
| 3 | **Linear interpolation between catalog openings is our choice, not the catalog's** | Cv at an opening between listed points, and opening for a required Cv, can be off where curves bend sharply (quick opening, butterfly near 90°) | Ask Emerson or an engineer what interpolation Fisher uses; measure the error on curves with known intermediate points |
| 4 | **Sections B and D are typed by a general converter, not per table.** `c14_table_value` holds 33,306 numbers from 423 tables (B 7,746; D 25,560) with row keys and column header paths. The second reader confirms all but 5 (on B-84, where the spring adjustor columns aren't row-aligned), but 4,580 are confirmed only as "all present within four lines" rather than in order on one line. Key columns are chosen by rules (header names, text columns), so some key names are odd (e.g. D-29's "Torques": "Operating"/"MAST"). 50 tables have no numbers (shaft/actuator compatibility matrices, equations, terminology) and are listed in `table_values_text_only.csv` | Queries need to know each table's key names and column paths; a wrong key choice would attach a value to the wrong row label without failing the row-order check | Hand-check a sample per layout; where a table is used by a tool, give it a typed table as done for the 7600 and 657 |
| 5 | **The tools read the CSV files; the database is built from them** | Two copies; tests keep them in agreement, but nothing structurally prevents drift | Point the tools at `fisher.db` and make the CSVs an intermediate build step |
| 6 | **Motion is mislabelled for tables without an opening axis** (SIS, Z500 ball valves are labelled sliding-stem) | Filters by `motion` return them in the wrong group | Set motion from the valve type, not only from the position axis; add a family-level override |

## 1. Not extracted

**Catalog 12**
- Pages 2-17 to 2-22: Fisher Sizing Program vapor pressure and pulp stock pages. They describe software rather than give data; the pulp stock correction charts (2-21, 2-22) are not digitized.
- Page 2-29: the critical pressure ratio (rc) charts. The FF equation is used instead; it agrees with the worked examples to about 0.01.
- Page 2-35: the saturated and superheated steam density chart.
- Pages 3-2 to 3-6: general sound characteristics (line and point sources, octave bands, combining noise sources, path treatments).
- Three-way butterfly guidance (pages 79–80): text and figures only.
- The prose of the sizing procedures is not stored as text. The equations are code instead.

**Catalog 14**
- Force method (B): valve body forces, 585C springless and 657/657R/667 selection are implemented. The 585C spring-biased, 685, 685SE/SR, 785C, 3025 and 657C tables, Table 17 (safe spring loads) and the stem load section (B-99 onward) are typed values in `c14_table_value`, but no tool uses them yet.
- Torque method (D): equations and the 7600 butterfly data are implemented. The A/B/C tables for every other valve (8532, 8560, 8580, A11, CV500, V150, V200, V300, V500, Control-Disk, 9500 and others), K factors, shaft strength by temperature (Table 3) and the actuator torque output tables are typed values in `c14_table_value`, but no tool uses them yet.
- Figures that pdfplumber reads as ruled tables (the 685 force charts on B-27) are skipped; the shaft/actuator compatibility matrices (D-123 onward) hold marks, not numbers, and are only stored as printed.
- Air-spring-effect charts (B-88 onward) and other figures are not digitized.
- Footnote text on Catalog 14 pages. Footnote numbers are kept on each value, but what they say is not (Catalog 12 has `page_note`; Catalog 14 does not).
- Text pages: sample calculations (B-77 onward), Bettis actuator sizing notes (D-84 onward), three-way butterfly application notes (D-100).
- Tables A-2, C-4 and C-5 (which constructions are covered, angles of rotation) are stored as printed but not used as structured data.

**Documents referred to but not available**
- PS Sheet 51.1:E Series(A), D104737X012 (Large ED/EWD, Large ET/EWT coefficients).
- PS Sheet 51.1:FB(A), D104710X012 (FB coefficients).
- The product bulletins the catalogs refer to (e.g. 51.1:ED, 51.4:020) for pressure-temperature ratings, materials and construction details.

- Catalog 14 Table 4 prints a second "TBX / Bore Seal" row (class IV, 80*PC) and an "EWND, 10.125" row; both are kept as printed, but which construction they mean is ambiguous.

## 2. Known limits of the extraction

- **Characteristic not stated:** 679 of 3,593 configurations (mostly butterfly and ball valves, where the catalog doesn't print it).
- **Flow direction not stated:** 408 configurations.
- **Inferred from the page:** where a page names exactly one characteristic or flow direction, it is applied to every table on that page. Not hand-checked on multi-table pages.
- **No port diameter and travel in inches:** 1,140 sliding-stem configurations. Mostly Baumann (24000 series, 51000, 83000, 84000, 26000), which print no travel, plus GX and D3. These can't link to Catalog 14 section A.
- **No size parsed:** 91 configurations: EH (42; sizes such as "1, 1 1/2 x 1, or 2 x 1"), 83000/81000/87000/89000 (sized by orifice), cage-level codes, and the Fd reference table.
- **Pressure class is not a column:** it sits in the title text (e.g. "CL125 - CL600") for 2,290 configurations. Trim and cage type are also title text only.
- **Shading:** restricted trim is detected from gray shading and "Restricted trim" footnotes. Shading with any other meaning would be reported as restricted trim. No other meaning has been seen, but not every legend was read.
- **Valve names in Catalog 14** are kept as printed in the heading (e.g. "8532, CL150, S17400 (H1025) Shaft", "Control-Disk™ Valve, CL150-CL300"); there is no normalized family column.
- **Every `max_dp` is printed twice in rotary tables** (bar and psi rows). Queries must filter on `unit`.

## 3. Errors in the catalogs themselves

Kept as printed and flagged in `catalog_flag`, never corrected. The true values are unknown.

- **243 warnings on 39 pages:** 203 Kv/Cv inconsistencies and 35 out-of-range values. Examples:
  - A11-6 prints a Cv of 178 as "078".
  - HP-49 prints every Kv as 0.00.
  - EZ-1 prints "14.7" as XT in the 6 mm column (a copied Cv).
  - EH-5 XT values above 1.
- **5 unreadable cells:** "0..696", "0..94", "0.6.6", ".9." (twice).
- **CV500-3:** a row labelled "Kv" holds values of 0.2–0.45. What it actually is (likely Kc or Fd) is unknown.
- **V200U-1 and V200U-2:** Kv rows don't track their Cv rows.
- **Liquid sample problem 3** prints N4 = 7600; Table 2 says 76000. The code uses 76000, the only value that reproduces the printed answer.
- **585 Cv-decreasing notes (info).** Most are real (three-way valves, characterized trims). Not reviewed one by one.

## 4. Approximations

| Item | Basis | Known difference |
|---|---|---|
| SPL_ΔP, ΔSPL_Cv, ΔSPL_Km, ΔSPL_G (noise) | Straight lines fitted to the chart images | 0.1–0.4 dB scatter; the worked example reads non-cavitating SPL_ΔP 1 dB higher (81 vs 79.9) |
| ΔSPL_Ar (noise) | Page 3-1 equation | The older page 3-10 chart differs by up to 18 dB at low Ar with high Km. Which one Fisher uses today is not stated beyond page 3-1 calling its equation the current method |
| Fm and critical ΔP/P1 (liquid-gas mixtures) | Points sampled from the chart images | About ±0.02; 0.458 vs the example's 0.475 |
| Reynolds number factor FR | Table 3, linear interpolation | The catalog states this is satisfactory; its worked example read 0.62 off the curve where the table gives 0.61 |
| Cv between openings | Linear interpolation | Unknown (item 3 above) |

## 5. Assumptions in linking valves to actuators

- **Sliding-stem matches need an exact port and travel.** If Catalog 14 lists the port at a different travel, the configuration doesn't link. Whether a rating at another travel can be used is an engineering question.
- **Valve coverage is taken from Catalog 14 page A-2** (D, ED, ES, ET, EZ, EWD, EWS, EWT). Other sliding-stem valves (EH, HP, GX, CAV4, Baumann, ...) are referred to the force method. GX is sized differently (page A-1 says each GX has a preselected actuator); that rule is not encoded.
- **EW pages naming several valves** ("EWT-2, EWD, and EWT") use the first one; the others are listed as `also_applies_to`. Since EWD is balanced Class II and EWT is balanced Class IV/V, the choice changes which rows apply.
- **Leakage class is not filtered by default.** The catalog's default class per valve is shown, but every class is returned unless one is chosen.
- **Rotary matches are by valve family name and NPS.** These names don't match automatically:
  - V200U (Catalog 12) vs V200 (Catalog 14): whether they're the same valve is unknown.
  - A31D: Catalog 12 says its coefficients equal the 8532's, but that isn't used for actuators.
  - 8540 and 8560: no Catalog 14 pressure drop tables.
- **Rotary opening angle:** Catalog 12 lists 10–90°, but Catalog 14 rates at a few angles (often 0, 60, 70 or 90). No rule picks the angle for an operating point; the user must choose. 0° is presumably shutoff.
- **Rotary families with no Catalog 14 pressure drop table:** 30,000, 8540, 8560, 8590, A31A-Cryogenic, A31D, V150S, V200U, V250, V260, V270, V280.
- **Bench set and supply** are kept as printed ranges, e.g. "0-33", "6-30". There's no check that an actuator's spring range suits a given signal or air supply.

## 6. What has not been independently verified

- **Catalog 12 coefficients:** checked by a second PDF reader, Kv/Cv and range checks, the worked examples, and your hand check of 20 tables.
- **Catalog 14 pressure-drop ratings:** checked by the second PDF reader and spot tests against printed values only. **No human hand check yet.**
- **Catalog 14 sections B and D:** all but 5 values confirmed by the second reader, 14% of them only loosely (item 4 above). No hand check.
- **Chart digitizations:** checked only against the catalogs' own worked examples and by eye.
- **Valve-to-actuator links:** unit-tested on a few configurations (e.g. ES NPS 3 → page A-3). Not reviewed by an engineer for correctness of the matching rules.
- **Sizing functions:** reproduce every printed worked example. Not compared with Fisher Specification Manager.

## 7. Tooling and data management

- The gas sizing function takes US units only. Metric use means choosing constants from `equation_constant` by hand.
- There is no dataset version or changelog. `data/fisher.db` (28.7 MB) is committed to git and rebuilt by `make data`.
- **New catalog editions:** the PDFs are pinned by SHA-256, so a new Emerson edition stops the build, but there's no automated diff of what changed.
- **Single-user UI:** it binds to localhost, with no authentication and no saved work.
- **No AI-assistant interface yet** (e.g. an MCP server over the dataset and functions).

## 8. Open questions for an engineer or Emerson

1. Which interpolation should be used between catalog openings?
2. Can a Catalog 14 rating listed at one travel be applied to the same port at a different travel?
3. Which ΔSPL_Ar does Fisher use today: the page 3-1 equation or the page 3-10 chart?
4. What does the CV500-3 row labelled "Kv" actually contain?
5. Is the Catalog 12 V200U the Catalog 14 V200?
6. What are the correct values behind the 243 flagged cells? Are corrected catalog editions available?
7. Are we permitted to store and share data derived from Emerson's catalogs? Who will use the dataset, and how widely?
