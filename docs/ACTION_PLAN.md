# Action Plan: Fisher Catalog 12 Data Extraction

**Source:** [Fisher Catalog 12 – Valve Sizing](https://www.emerson.com/is/content/emerson/en/final-control/flow-controls/documents/d103182x012.pdf) (398 pages)
**Page list:** [`page_inventory.csv`](page_inventory.csv), which gives each page's section, valve family and type
**Goal:** deterministic tools and lookups: the same input always gives the same answer, and every answer traces back to a catalog page.

## What's in it
| Section | Pages | Content | Use |
|---|---|---|---|
| 1. Flow coefficients | 3–343 | 287 tables of Cv, Kv, XT, FL, Fd for 64 valve families | Lookup data |
| 2. Sizing procedure | 344–386 | Sizing equations + worked examples | Calculator code + its tests |
| 3. Noise | 387–398 | Noise prediction, mostly charts | Later, if needed |

32 pages are blank and 9 only point to another valve's tables. These are skipped.

## Steps

**1. Extract the tables.** AI reads each coefficient page into one flat table, one row per value:

| family | pressure_class | trim | characteristic | flow_direction | nps | port_in | travel_in | coeff | position | value | page |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ED | CL125-600 | Quick Opening Cage | Quick Opening | Flow Down | 1-1/2 | 1.875 | 0.75 | Cv | 100 | 44.0 | ED-1 |

Plus a small `aliases.csv` for "same coefficients as" notes (e.g. EDR → ED).

**2. Check the data.**
- Automatic: Kv should be ≈ 0.865 × Cv, and Cv should rise with opening. Any page that fails gets re-read.
- By hand: compare about 20 random tables against the PDF.

Once checked, the data is frozen. The tools only read it; no AI is involved at run time.

**3. Build the lookups.**
- `get_coefficients(family, size, trim, ...)`: returns the table for one configuration.
- `cv_at(config, opening)` / `opening_for(config, cv)`: linear interpolation between catalog points.
- `find_valves(required_cv, ...)`: lists the configurations that reach the required Cv between about 20% and 80% open.

**4. Build the sizing calculator.** Turn the Section 2 equations into functions: liquid Cv, gas Cv, and the choked-flow limit. The catalog's worked examples become the tests, so each function must reproduce the printed answers.

## Output
- `data/coefficients.csv`, `data/aliases.csv`
- A small Python package with the lookup and sizing functions, plus tests

## Open question
Should it cover all 64 valve families, or start with a few?
