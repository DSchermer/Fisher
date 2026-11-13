# Action Plan: Extracting, Chunking, and Modeling Fisher Catalog 12

**Source:** Fisher Catalog 12, *ASME/ISA/IEC Valve Sizing* (part D103182X012, April 2022 edition, last modified Sep 2024)
**URL:** https://www.emerson.com/is/content/emerson/en/final-control/flow-controls/documents/d103182x012.pdf
**Size:** 398 pages, 4.0 MB, PDF 1.6, letter size, untagged, real text layer (no OCR needed)

The companion file [`page_inventory.csv`](page_inventory.csv) classifies every page. It is a first pass made with heuristics, so Phase 0 checks it before anything else relies on it.

**Execution model:** AI agents do the work (see section 3 of this plan); a person approves at three review gates.

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

## 3. Execution model: AI does the work, humans approve at gates

Everything below assumes **AI agents do the extraction, coding, chunking and modeling**, and a person only makes decisions and signs off. That changes the plan in three ways:

1. **Never trust one reading.** A vision model reading a dense numeric table will sometimes swap digits, shift a column, or fill a `‐‐‐` cell with a plausible number. Every coefficient is therefore read **two independent ways**, and only values both readings agree on are accepted automatically.
2. **Code checks, not AI opinion.** Validation is deterministic (Kv/Cv ratio, monotonicity, ranges, unit agreement). An LLM never grades its own extraction.
3. **Time is measured in hours of compute, not days of labor.** The limits are API cost, how many disagreements need adjudication, and how fast a person can clear the review gates.

### Roles

| Role | Who | Does |
|---|---|---|
| **Builder agent** | Claude Code (this kind of session) | Writes and runs the pipeline code, the deterministic parser, prompts, schemas, tests. Commits to this repo |
| **Extractor** | Claude Opus 5.5 (`claude-opus-5-5`) via the **Message Batches API** | Reads each page (single-page PDF = text layer + page image) and returns schema-constrained JSON |
| **Deterministic reader** | Python (`pdfplumber`), written by the builder agent | Reads the same page from word positions, cell rectangles and fill colors. No AI involved |
| **Adjudicator** | Claude Opus 5.5 at higher effort, with a zoomed crop of the disputed cells | Settles cells where the two readings disagree. It must cite the crop, and if it can't decide, the cell goes to a human |
| **Reviewer** | A person | Approves the schema and ontology, clears the human queue, signs off on a random audit sample |

### Claude API features used
- **Structured outputs** (`output_config.format` with a JSON schema) so every response parses. Citations can't be combined with structured outputs, so traceability comes from the deterministic reader's bboxes, not from model citations.
- **Message Batches**: 50% cheaper, asynchronous, results keyed by `custom_id` = `p{page}-{pass}`.
- **Prompt caching**: one frozen prefix (instructions + JSON schema + 2–3 worked page examples) cached across all ~300 requests. Only the page itself changes.
- **Input format:** split the catalog into one-page PDFs, so each request gets both the text layer and the rendered image. For the densest pages (EW, HP, ED-11/12, TBX), the pilot also tests sending the top and bottom halves as separate 2× crops, in case small digits get lost when the page image is downscaled.
- **Adaptive thinking**, effort `medium` for extraction and `high` for adjudication and equations.
- Prerequisite: an Anthropic API key available to the pipeline (stored as an environment secret, never committed).

---

## 4. Phased action plan (AI-executed)

### Phase 0 — Setup & pilot (builder agent, ~2–3 hours) · **Gate A**
- [ ] Repo skeleton: `src/`, `prompts/`, `schemas/`, `data/{source,raw,interim,final}/`, `tests/`. Store the PDF with its SHA-256.
- [ ] Builder agent checks and fixes `page_inventory.csv` by rendering pages and confirming page kinds.
- [ ] Draft `schemas/coeff_page.json` (compact *wide* form: one object per configuration, arrays of values per coefficient type, explicit `null` for `‐‐‐`, raw strings kept alongside parsed numbers, footnote markers split off).
- [ ] **Pilot on 12 pages chosen to cover every layout** (e.g. 1-1, 8532-1, 24000CVF-1, ED-1, ED-12, EW-4, HP-42, TBX-2, V150-1, V500-1, YD-1, A31A-1). Hand-verify them once to make a **gold set**.
- [ ] Measure on the gold set: cell accuracy, tokens and cost per page, and whether whole-page images or half-page crops do better.
- **Gate A (human, ~1 hour):** approve the schema, look at the pilot accuracy and cost, and confirm the decisions in §8. Nothing runs at scale before this.

### Phase 1 — Deterministic reader (builder agent, ~0.5–1 day of agent time)
- [ ] Per-page raw dump: words with bbox and font, rects with fill color, images (`data/raw/page_NNN.json`).
- [ ] Glyph-repair map keyed by font name (Interleaf/PSO symbol fonts).
- [ ] Rule-based table reader for the main layouts: header resolver (%-travel vs degrees), row-block grouping, size labels attached by vertical overlap, gray-fill → shading flag, footnote split.
- [ ] Doesn't need to be perfect. It's the *second opinion*. Any page it can't handle confidently is marked `det_status: low_confidence` and relies on the vision read plus adjudication.

### Phase 2 — AI extraction at scale (Batches API, ~1–6 hours wall clock)
- [ ] **Batch 1 — tables:** all 287 coefficient pages → JSON per the schema.
- [ ] **Batch 2 — everything else:** index pages, §2 text/tables/equations (equations returned as LaTeX plus symbol list), the 24 figures (type, axes, captions, and for the charts needed in calculations, *approximate* digitized points marked as such), the 9 redirect pages and ~33 "also appropriate for" notes as structured relationships.
- [ ] Store every raw response with model ID, prompt version and schema version, so any value can be traced to the call that produced it.

### Phase 3 — Reconcile & validate (code + adjudicator, ~2–4 hours)
1. **Align** the vision read and the deterministic read cell by cell (family, config, coefficient, position).
2. **Auto-accept** when they agree exactly *and* the value passes every check:
   - `Kv / Cv` between 0.85 and 0.88
   - mm ≈ 25.4 × in for ports and travel
   - `0 < XT ≤ 1`, `0.3 < FL ≤ 1`, `0 < Fd ≤ 1`
   - Cv non-decreasing with opening (violations flagged, not rejected: quick-opening plateaus and butterflies near 90° are real)
   - expected number of positions per row, NPS on the standard list
3. **Adjudicate** the disagreements: Opus 5.5 gets a 3× crop of just those cells plus both candidate values and must return one, or `unresolvable`.
4. **Human queue:** `unresolvable` cells, any check failure the adjudicator couldn't explain, and pages where both readers were low-confidence. *Expect this to be well under 5% of cells. Treat that as an estimate to confirm in the pilot.*
5. **Equations:** the builder agent turns each §2 equation into a Python function and runs the printed **worked sample problems as unit tests**. An equation is accepted only when its example reproduces the printed answer.

**Gate B (human, ~2–4 hours):** clear the human queue, then audit a **random sample of ~50 configurations against the rendered page** (the builder agent generates an overlay page: extracted values drawn over the PDF image). If the sample has any Cv/Kv error, find the cause, fix it, re-run the affected pages, and sample again.

### Phase 4 — Chunking (mostly code, some AI writing, ~2–3 hours)
Same chunk types as before. The difference is who writes what:

| Chunk type | Written by | Numbers come from |
|---|---|---|
| `coeff_config` (~2–4k) | **Code template** from verified data | Verified dataset only |
| `coeff_page_summary` (~287) | Code template | Verified dataset |
| `family_overview` (~64) | **AI-written** prose + code-inserted facts | Verified dataset + relationship edges |
| `procedure_step`, `worked_example` (~100–160) | AI segments §2–§3 into self-contained steps | Source text; equations from Phase 3 |
| `reference_table` (~15–25) | Code | Verified reference CSVs |
| `figure` (~24) | AI description | Figure metadata; digitized points marked approximate |

**Guardrail on AI-written chunks:** a script pulls every number out of each AI-written chunk and checks that it exists in that chunk's source data. Any chunk with an unmatched number is regenerated or flagged. This blocks invented values from getting into the knowledge base.

### Phase 5 — Conceptual model (AI proposes, human approves, ~2–3 hours) · **Gate C**
- [ ] The builder agent proposes the ontology (core entities in section 5 of this plan) from the verified data and the inventory, generates an ERD, and loads the graph (`graph/nodes.csv`, `graph/edges.csv`).
- [ ] AI pulls relationships from the note and redirect pages (`SHARES_COEFFICIENTS_WITH`, `DOCUMENTED_IN`). Code then checks each claimed "identical coefficients" link by comparing the two tables, and records disagreements instead of hiding them.
- [ ] Computes derived concepts: rangeability, characteristic-shape fit, Cv per NPS by valve style, coverage gaps.
- **Gate C (human, ~1 hour):** approve the ontology and spot-check the relationship list.

### Phase 6 — Packaging & regression (builder agent, ~1–2 hours)
- [ ] `coefficients.parquet`, reference CSVs, `chunks.jsonl`, graph CSVs, `catalog12.duckdb`, data dictionary, coverage matrix, validation report.
- [ ] The gold set becomes a **regression eval**. Any prompt, model or code change must still score 100% on it before re-running.
- [ ] One command re-runs everything, keyed by PDF hash, so the next catalog edition is extracted and diffed against this one automatically.

---

## 5. Conceptual model (target)
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
With this in place, an AI assistant can answer a sizing question by running a §2 procedure as code, finding the `TrimConfiguration`s whose Cv curve covers the required Cv, checking choked-flow limits with XT/FL, and giving the source page for every number. It reads numbers from the database through a tool call, never from memory or retrieved prose.

---

## 6. Time & cost estimate

| Item | Estimate |
|---|---|
| Builder-agent work (code, prompts, tests) | ~1–2 days elapsed, mostly unattended |
| Batch extraction wall clock | Usually a few hours; the Batches API allows up to 24 h |
| Human time at gates A + B + C | **~4–6 hours total**, mostly the Gate B audit |
| **API cost, rough** | Opus 5.5 is $4 / $20 per M input/output tokens, and Batches halve that. At ~4k input and ~5–9k output tokens (including thinking) per table page, extraction is roughly **$15–30 batched** for 287 pages. Adjudication, §2/§3 pages, chunk prose and re-runs add a similar amount. **Plan on ~$50–150 total**, and replace this with the real per-page cost measured in the pilot |

The cost is small next to the cost of one wrong Cv in a sizing decision, which is why the plan spends tokens on reading everything twice rather than saving them.

---

## 7. Risks specific to AI extraction

| Risk | Mitigation |
|---|---|
| Plausible-looking wrong digits | Two independent readings + Kv/Cv check + random human audit |
| Model fills `‐‐‐` / blank cells | Schema requires `null` + raw string; deterministic reader confirms the cell is empty |
| Column shift on misaligned rows | Deterministic reader uses cell rectangles, not text order. Monotonicity and Kv/Cv checks catch shifts |
| Footnote marker merged into value (`0.010(1)` → `0.0101`) | Schema field for footnote IDs. Deterministic reader splits on superscript font size |
| Shading missed or misread | Fill color comes from the PDF vector data, not just the image |
| Small digits lost when the page image is downscaled | Pilot compares whole page vs half-page 2× crops and picks per layout |
| Invented numbers in prose chunks | Number-membership check on every AI-written chunk |
| Same input, different output on re-runs | Store raw responses + model/prompt/schema versions; gold-set regression eval |
| Model refusals / API errors | Batch results checked per `custom_id`; failed or refused pages are re-queued, never silently dropped |
| Copyright | Emerson material: keep derived data internal unless you've confirmed rights to share it. Uploading to the API for processing is a separate question from redistributing |

---

## 8. Decisions needed before Gate A
1. **Main consumer:** RAG/chat assistant, sizing calculator, or analytics database? This decides how much goes into Phase 4 versus Phase 5.
2. **API access:** OK to send the catalog pages to the Anthropic API, and whose key/account pays for it?
3. **Units:** keep US and metric as printed, or normalize?
4. **Figures:** which charts must be digitized for calculations (approximate values), and which only need a description?
5. **Scope:** all 64 families or a priority subset first?
6. **Accuracy bar:** zero tolerated Cv/Kv errors in the audit sample (recommended), or a stated error rate?
