# For you in the morning

Everything that could be done without you has been done (see `docs/GAPS.md` and `docs/CHANGELOG.md`). These need
a decision, a hand check, or someone outside: none of them blocks using the tools.

## Decisions (made on your go-ahead to "make your own call")

1. **Sharing:** unchanged. The catalogs' prose is still not stored (closer to copying the documents); table
   footnotes are. Who may use data derived from Emerson's catalogs is still yours to decide.
2. **Interpolation: linear stays the default.** Fisher's own gas sample problem 1 (page 2-14) reaches 78% open with
   linear interpolation and 79% with the monotone cubic, so linear is what the catalog's worked example uses.
   `interp="pchip"` remains available; it fits the catalog's curves better (`docs/INTERPOLATION.md`).
3. **`data/fisher.db` is no longer committed.** It is built from the committed CSVs the first time it is used (about
   15 seconds, no PDFs needed) and rebuilt whenever a CSV changes (`fisher/db.py`). Old copies remain in git
   history; removing them would need a history rewrite, which I have not done.
4. **Merged into `main`.**

## Hand checks (about 15 minutes each)

5. **Rotary torque factors** (`torque_factor`, 17,962 values, 26 valves), classified by rule. Spot-check two or three
   rows per valve against the PDF, especially:
   - **K versus C:** tables with angle columns and no A/B/C are taken as K (gas ΔPeff = K·P1abs), as page D-10 says.
   - **30,000 valves** (D-29 to D-29.7): operating torques VRUN/VETC/VBTO and their MAST rows.
   - **Torque direction marks** (θ = tends to open, Κ = tends to close) attached to C at an angle.
6. **Actuator torque** (`actuator_torque`): action (PDTC/PDTO, spring-to-close/air-to-close) and size for a few 1051,
   1052, 1068 and 2052 rows.
7. **Merged cells.** A value printed once across several rows (e.g. a B factor shared by three bearings) is repeated
   on each row (`merged = 1`). A single value printed beside a stack of lines is taken to cover the whole stack.
   That held for every case checked; if a table ever means "first line only", this rule is wrong for it.
8. **Figure 4A** (TBX/CVX piston ring friction) was digitized from an image and its labels matched by order. Check
   two lines: e.g. 9.2 in reaches about 3,600 lb at 4,000 psi; 3.44 in about 1,100 lb.

## Questions for an engineer or Emerson

9. Validate 10–20 real sizing cases against Fisher Specification Manager / FIRST.
10. Can a Catalog 14 rating at one travel apply to the same port at another travel?
11. ΔSPL_Ar: page 3-1 equation or page 3-10 chart?
12. What does the CV500-3 row labelled "Kv" contain?
13. Is the Catalog 12 V200U the Catalog 14 V200? Should A31D use the 8532's actuator data?
14. Confirm the inferred corrections with Emerson (`docs/CORRECTIONS.md`: 204 high, 5 medium, 10 estimates, 4 unresolved).
    The 5 medium ones are worth a look first.
15. The 785C spring-return sizing procedure (the catalog prints springs and preloads but no procedure).
