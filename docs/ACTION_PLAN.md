# Action Plan: Extracting, Chunking, and Modeling Fisher Catalog 12

**Source:** Fisher Catalog 12, *ASME/ISA/IEC Valve Sizing* (part D103182X012, April 2022 edition, last modified Sep 2024)
**URL:** https://www.emerson.com/is/content/emerson/en/final-control/flow-controls/documents/d103182x012.pdf
**Size:** 398 pages, 4.0 MB, PDF 1.6, letter size, untagged, real text layer (no OCR needed)

The companion file [`page_inventory.csv`](page_inventory.csv) classifies every page. It is a first pass made with heuristics, so Phase 0 checks it before anything else relies on it.

---

## 1. What the document contains (from recon)

| Part | PDF pages | Printed labels | What it is | Data shape |
|---|---|---|---|---|
| Index | 1–2 | i–ii | Valve name → style → page label | Two-column dotted-leader lists |
| §1 intro | 3–4 | 1-1, 1-2 | Typical **Fd** valve style modifiers (IEC 534) | One small matrix: valve type × relative flow coefficient |
| **§1 Flow Coefficients** | 5–343 | `<FAMILY>-n` | Sizing coefficients for **64 valve families** (Fisher globe, angle, butterfly, ball, 3-way, Baumann) | **Dense numeric matrices**, the core dataset |
| §2 Sizing Procedure | 344–386 | 2-1 to 2-43 | ISA/IEC liquid and gas sizing, sample problems, FSP vapor pressure, pulp stock, leakage classes, cavitation/flashing, two-phase, steam tables, velocity | Prose, equations, reference tables, charts |
| §3 Noise Abatement | 387–398 | 3-1 to 3-12 | Hydrodynamic noise, ΔSPL corrections | Prose, equations, chart images |

**Page kinds (heuristic):** 287 coefficient tables · 54 text · 32 intentionally blank · 16 figure-dominant · 9 redirect/stub pages.

### Structure of a coefficient table
Each §1 page has a header block (family, pressure class such as `CL125 - CL600`, trim/cage type, flow direction, date) and a grid:

- **Row keys:** valve size (NPS), port diameter (mm and in), max travel (mm and in), sometimes trim/cage/seal variant
- **Coefficient rows** per configuration: `Cv`, `Kv`, `XT`, `FL`/`Fl`, `Fd` (not every table has every one)
- **Columns:** either *% of total travel* (10…100) for sliding-stem valves (~210 pages) or *rotation in degrees* (10…90) for rotary valves (~76 pages), plus extra columns such as "Coeffs for 6 mm travel" and `FL at 100%`
- **Characteristic:** Linear, Equal Percentage, Modified Equal Percentage, Quick Opening, and others
- **Footnotes** `(1)…(n)` attached to cells (e.g. `0.010(1)`), plus page-level "Notes:"

### Problems recon turned up
1. **Gray row shading carries meaning.** "Restricted trim" (33 pages) and similar legends mark rows by **fill color (gray 0.75)**, and plain text extraction drops it. The shading has to be read from vector rectangles.
2. **Merged/spanning cells.** NPS and port diameter span several coefficient rows, and both the layout and pdftotext output put the size label *in the middle* of its block, not on the first row.
3. **Some rows are misaligned.** XT rows often lose their column spacing (`0.556 0.744 0.724 …`), so column positions can't be trusted. Use cell geometry instead.
4. **Fonts with nonstandard symbols.** `InterleafSymbols`/`PSOucsdart…` fonts map `=` to `+`, `Δ` to `D`, `°` to `_`, `®` to `r`, `™` to `t`, and `©` to `E`, and they use U+2010 hyphens. You need a glyph-repair map, and §2 equations need special handling.
5. **Cross-references instead of data.** "Coefficients identical to the 8532", "also appropriate for EDR, ET, ETR", "found in PS Sheet 51.1:FB(A)". These are *relationships*, not empty pages.
6. **Figure-only content.** About 24 large raster images (pp. 79–80, 348, 350, 364–365, 372–373, 378, 388–397) hold curves such as pulp correction factors, cavitation index, and noise ΔSPL vs. G. There is no text to extract, so they have to be digitized or summarized.
7. **Index and label inconsistencies.** For example, a page is labeled `IC-2` while the family is `IC2`, and index page numbers don't always match printed labels. Treat the index as a hint and the printed page labels as the truth.
8. **Edition dates differ by page** (Jan 2018 to Apr 2022). Keep the per-page date in the provenance.

---

## 2. Target outputs

| Output | Purpose | Format |
|---|---|---|
| **Raw layer** | Lossless per-page extraction (words + bboxes + fonts, rects/fills, images) | `raw/page_NNN.json`, `raw/img/*.png` |
| **Coefficient dataset** | Queryable "long" table of every coefficient | Parquet/CSV + SQLite/DuckDB |
| **Reference tables** | Fd modifiers, abbreviations, leakage classes, steam tables, FSP constants | One CSV each + JSON schema |
| **Knowledge chunks** | Retrieval-ready text for RAG/LLM use | JSONL with metadata |
| **Concept model** | Entities and relationships (valve → trim → coefficient → sizing equation) | Graph (JSON-LD or Neo4j CSV) + ERD |
| **Validation report** | Proof the data is right | HTML/MD report per phase |

### Canonical coefficient record (long format)
```
coefficient_id     uuid
valve_family       "ED"
body_variant       "CL125-CL600"            # pressure class / body style
trim               "Quick Opening Cage"     # cage/plug/disk/ball/seal type
characteristic     "Quick Opening"
flow_direction     "Flow Down"
nps                "1-1/2"   (+ nps_numeric 1.5)
port_dia_mm/in     47.6 / 1.875
max_travel_mm/in   19 / 0.75       # null for rotary
restricted_trim    true/false      # from row shading
coefficient_type   Cv | Kv | XT | FL | Fd
position_basis     pct_travel | rotation_deg | fixed_travel_6mm | rated
position_value     10..100 | 10..90 | null
value              22.1
value_raw          "22.1" / "0.010(1)"
footnote_ids       [1]
source_page        120   printed_label "ED-1"   page_date "2018-02"
bbox               [x0,y0,x1,y1]   # for traceability back to PDF
```
A wide view (one row per configuration with columns for each position) is generated *from* the long table, never the other way round.

---

## 3. Phased action plan

### Phase 0 — Setup & inventory (0.5 day)
- [ ] Repo layout: `src/` (pipeline), `data/raw|interim|final/`, `docs/`, `tests/`. Store the PDF under `data/source/` with its SHA-256 so a new edition can be detected.
- [ ] Toolchain: `pdfplumber` (words, rects, fills; already confirmed working), `pymupdf` (fast render/images), `poppler-utils`, `pandas`/`duckdb`, `pydantic` for schemas.
- [ ] Spot-check `page_inventory.csv` (page_kind, family) by hand and fix it. It drives every later phase.
- [ ] **Exit:** each of the 398 pages has a family, kind, and printed label everyone agrees on.

### Phase 1 — Lossless raw extraction (1 day)
- [ ] Per page: dump `chars/words` (text, x0/x1/top/bottom, fontname, size), `rects` (with `non_stroking_color`), `lines`, and images to JSON.
- [ ] Build a **glyph-repair map** for the Interleaf/PSO symbol fonts (`+`→`=`, `D`→`Δ` in Symbol font only, `_`→`°`, U+2010→`-`, etc.), applied **by font name**, never as a global replace.
- [ ] Render every page to PNG at 150 dpi (QA and figure work) and export the 24 large images.
- [ ] Strip boilerplate: copyright footer, disclaimer, trademark block, "Catalog 12" header. Keep the date and printed label as metadata.
- [ ] **Exit:** the raw layer re-renders to text matching `pdftotext -layout` for ~20 sample pages.

### Phase 2 — Coefficient table extraction (§1, 287 pages) (3–5 days, the bulk of the work)
Do this as a **template-driven** parser, not one generic table finder:
1. **Page header parser:** family, body/pressure class, trim, flow direction, characteristic (top-right label), date.
2. **Grid detection:** use the ~500–1300 cell rectangles per page as cell boundaries (pdfplumber `table_settings` with `"lines"`/`explicit` strategies). Fall back to word-x clustering against header column centers when rects are missing.
3. **Column header resolver:** decide whether the axis is *% travel* or *degrees*, read the position values, and spot the special columns (6 mm travel, FL at 100%).
4. **Row-block assembler:** group consecutive `Cv/Kv/XT/FL/Fd` rows into one *configuration*, then attach the spanning NPS/port/travel cells by **vertical overlap** with the block (because the labels sit mid-block).
5. **Shading detector:** match each row's bbox against gray-filled rects, then set `restricted_trim` (or whatever the page legend says the shading means).
6. **Footnote resolver:** pull `(n)` markers off cell values and link them to the page's footnote text.
7. **Template families:** cluster pages by header signature (expect about 6–10 layouts, e.g. globe-%travel, rotary-degrees, Baumann, butterfly with disk-type columns, YD/YS 3-way). Write and test one template per cluster, starting with the biggest (EW, HP, ED, EH, V150, 30,000).
- [ ] **Exit:** each table page produces records that pass Phase 5 checks. Failures go to a `needs_review` queue with the page image.

### Phase 3 — Reference tables, procedures & figures (§1 intro, §2, §3) (2–3 days)
- [ ] **Structured tables:** Fd modifier table (1-1), abbreviations/terminology (2-2), numerical constants N1…N9 tables, leakage classes (2-27), saturated steam P/T (≈2-32/2-33), piping/velocity tables. Each gets its own CSV and schema.
- [ ] **Equations:** rebuild each sizing equation as LaTeX + a **Python function** (liquid Cv, gas Cv with Y/xT/Fk, FP, FLP, ΔPmax, FR, FF, velocity, two-phase). Use the *worked sample problems* (2-8…2-16, 2-29…2-32) as unit tests: run each one and check that the computed answer matches the printed result.
- [ ] **Figures (24 images):** sort them into (a) digitize, for curves needed in calculations such as pulp correction factors, FF vs Pv/Pc, ΔSPL vs G, using WebPlotDigitizer or a scripted digitizer, then save points and record the digitization error, and (b) describe only, for illustrations. Every figure gets a caption chunk either way.
- [ ] **Redirects (9 pages) & "also appropriate for" notes (≈33 pages):** write them as `SHARES_COEFFICIENTS_WITH` / `SEE_EXTERNAL_DOC` edges, not as data copies.

### Phase 4 — Chunking for retrieval (1–2 days)
Chunk **by meaning, not by token count**. This document is mostly numbers, so naive splitting breaks tables apart and loses their headers.

| Chunk type | Unit | Content | Est. count |
|---|---|---|---|
| `coeff_config` | One valve configuration (family + class + trim + characteristic + direction + NPS + port) | Header context + a small markdown table of Cv/Kv/XT/FL/Fd across positions + footnotes | ~2,000–4,000 |
| `coeff_page_summary` | One table page | "ED CL125–600 Quick Opening, Flow Down: NPS 1–3, ports 33.3–87.3 mm, rated Cv 22–161" + list of child chunk IDs | ~287 |
| `family_overview` | One valve family | Style, pages, variants, characteristics, pressure classes, shared-coefficient links, external refs | ~64 |
| `procedure_step` | One numbered step / subsection in §2–§3 | Prose + its equations (LaTeX) + symbol definitions inlined | ~80–150 |
| `worked_example` | One sample problem, start to finish | Givens → steps → answer, kept together | ~10–15 |
| `reference_table` | One reference table (or a logical slice of the big steam table) | Markdown table + caption + units | ~15–25 |
| `figure` | One figure | Caption, axes, description, link to digitized CSV | ~24 |

Rules:
- **Every chunk carries context in its own text**, so it is understandable when retrieved alone. Repeat the family, class, trim, characteristic, flow direction and units in the chunk body.
- Metadata on every chunk: `source_page`, `printed_label`, `section`, `valve_family`, `chunk_type`, `page_date`, `parent_id`, `related_ids`.
- Numbers are **answered from the structured store, not from text chunks**. Chunks are for finding the right configuration and explaining it. Exact values come from a SQL/tool call against the coefficient table, so the model never makes up a Cv.
- Target 200–800 tokens per chunk. Never split a configuration block or a worked example.

### Phase 5 — Validation (runs alongside Phases 2–4, ~2 days total)
**Automatic checks (all coefficient records):**
- `Kv ≈ 0.865 × Cv` (±1–2% rounding). This is the strongest consistency check available, and it catches column shifts immediately.
- Cv increases monotonically with travel/rotation (flag any violation, since some are real, e.g. QO plateaus or butterfly near 90°).
- Range sanity: `0 < XT ≤ ~1`, `0.3 < FL ≤ 1`, `0 < Fd ≤ 1`.
- Every configuration has the expected number of positions. NPS values are on the standard list. mm and inch columns agree (port_mm ≈ 25.4 × port_in).
- Every value traces back to a bbox on its source page.

**Manual checks:**
- Visual diff: overlay the extracted cell values on the rendered page PNG for 1 random page per template cluster plus all flagged pages.
- Double entry: hand-key 2% of configurations and measure the error rate (target: 0 errors on Cv/Kv).
- Equations: all worked examples reproduce their printed answers.

### Phase 6 — Conceptual model (1–2 days, can begin after Phase 2 templates stabilize)
**Core entities**
```
Manufacturer ─< ValveFamily ─< BodyVariant(pressure class, style) ─< TrimConfiguration
     (Fisher, Baumann)   (ED, V150…)                                 (cage/plug/ball/disk/seal,
                                                                       characteristic, flow direction,
                                                                       port Ø, max travel, restricted?)
TrimConfiguration ─< CoefficientCurve(type: Cv|Kv|XT|FL|Fd) ─< CoefficientPoint(position, value)
ValveFamily ─ SHARES_COEFFICIENTS_WITH ─ ValveFamily        (8532↔8540, ED→EDR/ET/ETR, EAD→EAS/EAT …)
ValveFamily ─ DOCUMENTED_IN ─ ExternalDoc                   (Bulletin 51.1:ED, PS Sheet 51.1:FB(A) …)
SizingEquation ─ USES ─ Parameter(Cv, FL, XT, Fd, FP, Y, Fk, N-constants …)
SizingProcedure(liquid | gas | cavitating/flashing | two-phase | pulp | noise) ─< Step ─ USES ─ SizingEquation
Parameter ─ DEFINED_BY ─ TerminologyEntry (Table 1, page 2-2)
CoefficientCurve.type ─ IS_A ─ Parameter                    ← the link that connects data to procedures
```
That last edge is what makes the data *usable*: a tool can take service conditions, run the §2 procedure, find candidate `TrimConfiguration`s whose Cv curve covers the required Cv at a sensible travel, and check the XT/FL limits for choked flow. All of it can be traced back to page and cell.

**Derived concepts worth computing once the data is extracted**
- Rangeability per configuration (Cv@max / Cv@min usable)
- Inherent characteristic fit (classify curve shape and compare it to the stated characteristic)
- Cross-family comparison: Cv per NPS by valve style (globe vs. ball vs. butterfly capacity)
- Gaps: families/configurations missing XT, FL, or Fd

### Phase 7 — Packaging & documentation (1 day)
- [ ] `data/final/coefficients.parquet`, `reference/*.csv`, `chunks.jsonl`, `graph/*.csv`, `catalog12.duckdb`
- [ ] Data dictionary + ERD diagram + per-family coverage matrix (which coefficient types exist per family)
- [ ] Re-runnable pipeline (`make extract chunk model validate`) keyed on the PDF hash, so the next catalog edition can be diffed

---

## 4. Order of work & effort

| # | Phase | Effort | Depends on |
|---|---|---|---|
| 0 | Setup & inventory | 0.5 d | — |
| 1 | Raw extraction | 1 d | 0 |
| 2 | Coefficient tables | 3–5 d | 1 |
| 3 | Reference/procedures/figures | 2–3 d | 1 (parallel with 2) |
| 4 | Chunking | 1–2 d | 2, 3 |
| 5 | Validation | ~2 d (continuous) | 2, 3 |
| 6 | Conceptual model | 1–2 d | 2 |
| 7 | Packaging | 1 d | all |
| | **Total** | **~11–16 working days** | |

**Fastest route to something useful:** do Phase 0 → 1 → Phase 2 for the single biggest template cluster (e.g. EW/HP globe %-travel) → Kv/Cv check → a `coeff_config` chunk sample. That gives a working end-to-end slice in about 3 days and shows how far the template approach scales.

## 5. Risks & mitigations
| Risk | Mitigation |
|---|---|
| Shading meaning varies by page (not always "restricted trim") | Read the legend text next to the shaded swatch on each page and store it as `shading_meaning` |
| Rare layouts break templates | `needs_review` queue + page image; hand-key the long tail if it's < 5% |
| Symbol-font misreads in equations | Rebuild §2 equations by hand from rendered images, then verify them with the worked examples |
| Digitized curves are imprecise | Store digitization uncertainty and mark such values `approximate` |
| Licensing/redistribution | This is copyrighted Emerson material. Keep derived datasets internal unless usage rights are confirmed |
| Newer catalog editions | Pipeline keyed on PDF hash + per-page dates, so a diff report shows changed pages |

## 6. Decisions needed
1. **Main consumer:** RAG/chat assistant, a sizing calculator, or an analytics database? This sets how much effort goes into Phase 4 versus Phases 3 and 6.
2. **Units:** keep both US (Cv, in) and metric (Kv, mm) as printed, or normalize to one and derive the other?
3. **Figures:** which charts actually have to be digitized for calculations?
4. **Scope:** all 64 families, or a priority subset (e.g. only the valves in your installed base)?
