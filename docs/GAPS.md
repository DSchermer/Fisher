# Gaps and unknowns

The state of the unified dataset (`data/fisher.db`, version in `dataset_info`) and tools after the
2026-11-13 gap-filling pass. Numbers come from the current data. Items that need a person (a decision, a hand
check, or Emerson) are collected in `docs/MORNING.md`.

## Most important first

| # | Gap | Why it matters | To close it |
|---|---|---|---|
| 1 | **No engineer has validated results against Fisher's own software** (Fisher Specification Manager / FIRST) | The tests reproduce the catalogs' own worked examples (C12 sizing, C14 B-77 to B-81, B-99, D-100, D-113), which is not the same as matching the current product software | Run 10–20 real cases through both and compare (MORNING) |
| 2 | **Typed sections B and D are classified by rule, not checked by hand** | 35,132 values (B 8,319; D 26,813) carry row keys and column paths chosen by rules; `torque_factor` (17,962 values, 26 valves) and `actuator_torque` (7,570) are classified from them. All values are confirmed by the second reader, but that checks the numbers, not that a number is under the right key | Hand-check a few rows per layout (MORNING items 5–6) |
| 3 | **Interpolation between catalog openings: measured, not decided** | Linear (the default) has a median error of 1–10% on the catalog's own curves when points are left out; monotone cubic (`interp="pchip"`) has the smallest error in 31 of 32 groups (`docs/INTERPOLATION.md`). Which one Fisher uses is unknown | Choose a default (MORNING) |
| 4 | **Equations without code:** SIS (D-98.2) and Z500 (D-122.1) torque equations; 785C spring-return sizing (the catalog prints the springs, preloads and rates but no procedure); U valve travel multipliers (D-103) | Their factors are typed and queryable, but no function computes a result | Code them from the printed equations; ask Emerson for the 785C spring-return procedure |
| 5 | **Tools read the intermediate CSVs; the database is built from them** | Now checked: `build_input` records each CSV's SHA-256 and a test fails if one changes without a rebuild. The tools themselves still read CSVs | Optional: move the tools to `fisher.db` |

## 1. Not extracted

**Catalog 12**
- Pages 2-17 to 2-22: Fisher Sizing Program vapor pressure and pulp stock pages (software description); the pulp stock correction charts (2-21, 2-22) are not digitized.
- Page 2-29: the critical pressure ratio (rc) charts. The FF equation is used instead (agrees with the worked examples to about 0.01).
- Page 2-35: the saturated and superheated steam density chart (the saturated steam table is extracted).
- Pages 3-2 to 3-6: general sound characteristics (text).
- Three-way butterfly guidance (pages 79–80): text and figures only.
- Procedure prose is not stored as text; the equations are code. Storing prose is held for the sharing decision (MORNING item 1).

**Catalog 14**
- Air-spring-effect charts (B-88 onward) and the 685 force charts (B-27, figure A): not digitized. The figure 4 (vector) and figure 4A (raster) piston ring friction charts are.
- Bettis G (D-83) and FieldQ (D-94) actuator pages: no ruled tables; FieldQ ratings in section C are extracted.
- Shaft/actuator compatibility matrices (D-123 onward; marks rather than numbers): stored as printed only. 50 tables with no numbers are listed in `data/catalog14/table_values_text_only.csv`.
- Text pages (sample calculations, sizing notes): used to write and test the code, not stored.

**Documents referred to but not available**
- PS Sheet 51.1:E Series(A), D104737X012 (Large ED/EWD, Large ET/EWT coefficients).
- PS Sheet 51.1:FB(A), D104710X012 (FB coefficients).
- The product bulletins the catalogs refer to (e.g. 51.1:ED, 51.6:8590, GX) for ratings, materials and construction details.

## 2. Known limits of the extraction

- **Characteristic not stated:** 679 configurations. **Flow direction not stated:** 408. Mostly butterfly and ball valves, where the catalog doesn't print them. Left blank, not guessed.
- **No port diameter and travel in inches:** 1,062 sliding-stem configurations, mostly Baumann (which prints no travel) and GX (which has preselected actuators). These can't link to Catalog 14 section A.
- **No size:** 38 configurations, all sized by orifice (Baumann 81000, 83000, 87000, 89000) or not a valve (Fd style modifiers). EH cage codes, "All Sizes" ranges and sizes in titles are now parsed.
- **Pressure class** is now a column (`valve_config.pressure_class`, `class_min`, `class_max`) for the 2,290 configurations whose titles state it. Trim and cage type are still title text.
- **Shading** is read as restricted trim. No other meaning of shading has been seen, but not every legend was read.
- **Every `max_dp` is printed twice in rotary tables** (bar and psi rows); queries must filter on `unit`.
- **Merged cells:** a value printed once across several rows is repeated on each (`merged = 1`). A single value beside a stack of lines is taken to cover the whole stack. That held for every case checked (MORNING item 7).
- **Catalog 14 Table 4** prints a second "TBX / Bore Seal" row and an "EWND, 10.125" row. Both are kept as printed; which construction they mean is ambiguous.

## 3. Errors and inconsistencies in the catalogs themselves

Kept as printed and flagged, never corrected.

- **243 warnings on 39 Catalog 12 pages** (`catalog_flag`): 203 Kv/Cv inconsistencies and 35 out-of-range values. Examples: A11-6 prints Cv 178 as "078"; HP-49 prints every Kv as 0.00; EZ-1 prints "14.7" as XT; EH-5 has XT above 1.
- **5 unreadable cells:** "0..696", "0..94", "0.6.6", ".9." (twice).
- **CV500-3:** a row labelled "Kv" holds 0.2–0.45; what it is (likely Kc or Fd) is unknown.
- **V200U-1 and V200U-2:** Kv rows don't track their Cv rows.
- **Liquid sample problem 3** prints N4 = 7600; Table 2 says 76000. The code uses 76000.
- **Catalog 14 D-114 Table 8** (sample actuator torques 12,130, 13,087, 13,488 ...) differs slightly from the catalog's own Table 5, which it cites (12,105, 13,081, 13,443 ...). The tools use Table 5.
- **Catalog 14 B-99 example** interpolates 6,810 lb at 750 °F. Interpolating the printed pounds gives 6,805 (the catalog interpolated in kN).

## 4. Approximations

| Item | Basis | Known difference |
|---|---|---|
| SPL_ΔP, ΔSPL_Cv, ΔSPL_Km, ΔSPL_G (noise) | Straight lines fitted to the chart images | 0.1–0.4 dB scatter; the worked example reads non-cavitating SPL_ΔP 1 dB higher (81 vs 79.9) |
| ΔSPL_Ar (noise) | Page 3-1 equation | The older page 3-10 chart differs by up to 18 dB at low Ar with high Km |
| Fm and critical ΔP/P1 (liquid-gas mixtures) | Points sampled from the chart images | About ±0.02; 0.458 vs the example's 0.475 |
| Reynolds number factor FR | Table 3, linear interpolation | The catalog says linear interpolation is satisfactory |
| Cv between openings | Linear (default) or pchip | Measured: `docs/INTERPOLATION.md` |
| TBX/CVX piston ring friction (figure 4A) | Slopes digitized from the image | About ±3%; figure 4 (EHD/HPD) is exact (vector) |
| Metric gas sizing | Catalog 12 Table 2 metric constants | Agrees with US units to 0.2% (constant rounding) |

## 5. Assumptions in linking valves to actuators

- **Sliding-stem matches need an exact port and travel.** Whether a rating at another travel can be used is an engineering question (MORNING).
- **Valve coverage comes from Catalog 14 page A-2** (D, ED, ES, ET, EZ, EWD, EWS, EWT). Other sliding-stem valves use the force method. GX now reports page A-1's preselected-actuator rule.
- **EW pages naming several valves** use the first; the others are listed as `also_applies_to`.
- **Leakage class is not filtered by default.**
- **Rotary matches are by valve family name and NPS.** V200U (C12) vs V200 (C14), and A31D (C12 says its coefficients equal the 8532's), are not joined automatically (MORNING). Rotary valves without a section C table now point to the torque method when typed factors exist.
- **Rotary opening angle:** for the 9500, V150/V200/V300 and V500, page C-5 Table 2 gives the angles to check (`actuators.required_angles`). For other valves the user still chooses.
- **Bench set and supply** are kept as printed ranges. Nothing checks that an actuator's spring range suits a given signal.
- **Rotary actuator selection** compares the actuator's torque at each angle the valve needs. Where the actuator table prints fewer angles, the smallest printed dynamic torque is used, and this is noted.

## 6. What has not been independently verified

- **Catalog 12 coefficients:** checked by a second PDF reader, Kv/Cv and range checks, the worked examples, and your hand check of 20 tables.
- **Catalog 14 pressure-drop ratings:** second reader and spot tests only. No hand check yet.
- **Catalog 14 sections B and D:** second reader (35,132 values: 33,609 in order on one line, 1,397 within four lines, 126 only found on the page) and spot tests against printed values. No hand check.
- **Chart digitizations:** checked against the catalogs' worked examples and by eye.
- **Valve-to-actuator links and actuator selections:** unit-tested on catalog examples; not reviewed by an engineer.

## 7. Tooling and data management

- **Dataset version and drift:** `dataset_info` (version, build time, source SHA-256s), `build_input` (SHA-256 of every CSV), `docs/CHANGELOG.md`, and `extract/diff_dataset.py` to compare two builds (e.g. a new catalog edition).
- **AI-assistant interface:** `fisher.mcp_server` (MCP over stdio) offers every command as a tool.
- **`data/fisher.db` is 46.7 MB and committed to git.** Every rebuild adds a new copy to the history (MORNING).
- **Single-user UI:** binds to localhost, with no authentication and no saved work. The new commands (valve torque, rotary actuator, stem load) are available from the CLI and MCP but have no UI form yet.

## 8. Open questions for an engineer or Emerson

1. Which interpolation between catalog openings should be the default?
2. Can a Catalog 14 rating listed at one travel be applied to the same port at a different travel?
3. Which ΔSPL_Ar does Fisher use today: the page 3-1 equation or the page 3-10 chart?
4. What does the CV500-3 row labelled "Kv" actually contain?
5. Is the Catalog 12 V200U the Catalog 14 V200?
6. What are the correct values behind the 243 flagged cells? Are corrected editions available?
7. What is the 785C spring-return sizing procedure?
8. Are we permitted to store and share data derived from Emerson's catalogs? Who will use the dataset?
