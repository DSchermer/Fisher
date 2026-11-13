# For you in the morning

Everything that could be done without you has been done (see `docs/GAPS.md` and `docs/CHANGELOG.md`). These need
a decision, a hand check, or someone outside: none of them blocks using the tools.

## Decisions (yours)

1. **Can the dataset be shared, and with whom?** It holds values typed from Emerson's copyrighted catalogs. I did
   **not** store the catalogs' prose (procedures, sample-calculation text) in the database, because that is closer
   to copying the documents; table footnotes are stored. Say if you want the prose too.
2. **Interpolation default.** Linear is the default. `interp="pchip"` (monotone cubic) is about twice as accurate on
   the catalog's own curves in 31 of 32 groups (`docs/INTERPOLATION.md`). Switching the default changes every
   in-between result slightly. My recommendation: switch to pchip once an engineer agrees.
3. **Stop committing `data/fisher.db`?** It is 46.7 MB and every rebuild adds a full copy to git history (about eight
   copies were committed tonight). Options: keep committing (simplest), Git LFS, or build it with `make data` and
   publish it as a release file. A history rewrite to remove old copies would need your explicit go-ahead.
4. **Merge into `main`?** All of this work is on `claude/zealous-turing-s1b964`.

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
14. The correct values behind the 243 flagged catalog cells.
15. The 785C spring-return sizing procedure (the catalog prints springs and preloads but no procedure).
