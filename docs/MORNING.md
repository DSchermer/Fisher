# For you in the morning

Decisions and checks only you (or an engineer, or Emerson) can make. Everything else in `docs/GAPS.md` is being worked through without waiting on these.

## Decisions

1. **Can the dataset be shared, and with whom?** (GAPS §8 q7.) The database holds values typed from Emerson's copyrighted catalogs. I have **not** stored the catalogs' prose (procedures, sample-calculation text) as text in the database, because that is closer to copying the documents themselves. Say if you want it stored.
2. **Merge into `main`?** All of this work is on `claude/zealous-turing-s1b964`.

## Hand checks (about 15 minutes each)

3. **Rotary torque factors** (`torque_factor`, 17,962 values, 26 valves). They are classified by rule from the printed headers. Spot-check two or three rows per valve against the PDF, especially:
   - which tables are **K** (gas ΔPeff = K·P1abs) and which are **C** (dynamic torque). Tables with angle columns and no A/B/C are taken as K, because page D-10 says so; C-factor tables printed on their own are taken as C.
   - **30,000 valves** (D-29 to D-29.7): operating torques VRUN/VETC/VBTO and their MAST rows.
   - **SIS and Z500**: these have their own equations (E, F, break and run factors), which are stored but not used in a calculation yet.
4. **Merged cells.** A value printed once across several rows (e.g. a B factor shared by three bearings) is now repeated on each row it covers (`merged = 1`). If a catalog ever prints a single value beside a stack that applies to only the first line, this rule would be wrong for that table.

## Questions for an engineer or Emerson (unchanged from GAPS §8)

5. Which interpolation between catalog openings?
6. Can a Catalog 14 rating at one travel apply to the same port at another travel?
7. ΔSPL_Ar: page 3-1 equation or page 3-10 chart?
8. What does the CV500-3 row labelled "Kv" contain?
9. Is the Catalog 12 V200U the Catalog 14 V200?
10. The correct values behind the 243 flagged catalog cells.
