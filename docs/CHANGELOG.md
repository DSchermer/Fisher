# Dataset changelog

The version is stored in `data/fisher.db` (`SELECT * FROM dataset_info`) and set in `extract/build_db.py`
(`DATASET_VERSION`). To see what a rebuild changed, keep the old database and run
`python extract/diff_dataset.py old.db data/fisher.db`.

## 2026.11.13

Source editions: Catalog 12 D103182X012 (SHA-256 c40ea5fe…), Catalog 14 D103428X012 (SHA-256 869ca15d…).

Added
- `c14_table_value`: every Catalog 14 force (B) and torque (D) table typed, with row keys, column paths,
  merged-cell repeats, captions, and second-reader results.
- `torque_factor`: A, B, C, K, MAST, shaft strength and valve-specific factors for 26 rotary valves.
- `actuator_torque`: 1051, 1052, 1061, 1068, 2052 actuator torque output.
- `stem_load_usage`, `stem_load_316`, `stem_material_factor`, `stem_reference_load`, `stem_load_valve`:
  the stem load section (B-99 to B-105).
- `actuator_3025`: 3025 available force (B-73 to B-76).
- `c14_page_note`: Catalog 14 table footnotes.
- `valve_config.pressure_class`, `class_min`, `class_max`; `actuator_rating.valve_family`.
- `dataset_info`, `build_input` (drift check).

Changed
- `valve_config.motion`: SIS and Z500 are rotary; Fd style modifiers are 'reference'.
- Sizes found for 53 more configurations (EH cage codes, 'All Sizes' ranges, size in title).
- `torque_characteristic`: 9 rows of the 7600 NPS 72 MAST (228,406 lbf-in) were empty; fixed.

## Earlier

Catalog 12 coefficients, reference tables, noise and two-phase charts; Catalog 14 pressure drop ratings,
force method tables, the 7600 torque data and valve-to-actuator links (see git history).
