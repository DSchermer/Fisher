# Action Plan: Fisher Catalog 12 Data Extraction

**Source:** [Fisher Catalog 12 – Valve Sizing](https://www.emerson.com/is/content/emerson/en/final-control/flow-controls/documents/d103182x012.pdf) (398 pages)
**Page list:** [`page_inventory.csv`](page_inventory.csv), which gives each page's section, valve family and type

## What's in it
| Section | Pages | Content |
|---|---|---|
| 1. Flow coefficients | 3–343 | 287 tables of Cv, Kv, XT, FL, Fd for 64 valve families (the main data) |
| 2. Sizing procedure | 344–386 | Sizing equations, worked examples, reference tables |
| 3. Noise | 387–398 | Noise prediction, mostly charts |

32 pages are blank and 9 only point to another valve's tables. These are skipped.

## Steps

**1. Extract.** AI reads each page and returns JSON:
- One record per valve configuration: family, pressure class, trim, characteristic, flow direction, size, and the values at each % of travel or degree of rotation.
- Section 2–3 pages become plain text plus any tables.

**2. Check.**
- **Automatic:** Kv should be ≈ 0.865 × Cv. If it isn't, the numbers were misread, so re-read that page.
- **By hand:** compare about 20 random tables against the PDF.

**3. Chunk.**
- Coefficient tables: one chunk per valve configuration, with the valve details repeated in each chunk.
- Sections 2–3: one chunk per topic or worked example.
- Every chunk keeps its page number.

**4. Organize.** One simple structure:
```
Valve family → configuration → coefficient values (by opening)
```
Add a note where the catalog says one valve uses another's coefficients (e.g. ED → EDR, ET).

## Output
- `coefficients.csv`: all table data
- `chunks.jsonl`: text chunks for search or AI use
- `valves.json`: family and configuration list

## Open questions
1. What will this be used for: an AI assistant, a sizing tool, or a database?
2. All 64 valve families, or start with a few?
