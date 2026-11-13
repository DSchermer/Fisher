"""Inferred corrections to Catalog 12 errors (extract/corrections.py, docs/CORRECTIONS.md)."""
import csv
import unittest
from pathlib import Path

from fisher import Catalog, db

ROOT = Path(__file__).resolve().parent.parent


def corrections():
    with open(ROOT / "data" / "corrections.csv", encoding="utf-8") as fh:
        return {(r["config_id"], r["coefficient"], r["position"]): r for r in csv.DictReader(fh)}


class Corrections(unittest.TestCase):
    def test_every_flag_resolved(self):
        with open(ROOT / "data" / "flags.csv", encoding="utf-8") as fh:
            flags = [f for f in csv.DictReader(fh) if f["severity"] != "info"]
        self.assertEqual(len(corrections()), len(flags))

    def test_known_cases(self):
        c = corrections()
        cases = {("107-1-6", "XT", "50"): (0.696, "high"),      # '0..696'
                 ("70-1-5", "Cv", "20"): (178, "high"),         # A11-6 '078': 0.865 x 178 = 154 = printed Kv
                 ("12-1-6", "Kv", "40"): (952, "high"),         # 8540-2 '95.2': decimal point
                 ("139-1-10", "Cv", "100"): (432, "high"),      # EH-2 '4312': Kv 373.68 = 0.865 x 432
                 ("98-1-5", "Kv", "30"): (2.51, "high"),        # D3-1 Kv 30/40 swapped
                 ("98-1-5", "Kv", "40"): (2.77, "high"),
                 ("336-1-1", "XT", "20"): (0.422, "high"),      # YD-3 '422'
                 ("233-2-1", "Kv", "60"): (7.85, "high"),       # HP-11 Kv repeats the Cv
                 ("271-1-1", "Kv", "100"): (0.536, "high"),     # HP-49 Kv row all 0.00
                 ("13-1-3", "Cv", "60"): (698, "medium")}       # typo reproduces Kv 604, but curve prefers 598
        for key, (value, conf) in cases.items():
            self.assertAlmostEqual(float(c[key]["corrected"]), value, places=3, msg=key)
            self.assertEqual(c[key]["confidence"], conf, key)

    def test_estimates_and_unresolved(self):
        c = corrections()
        self.assertEqual(c[("201-1-3", "XT", "Coeffs. for 6 mm (0.25 Inch ) Travel(2)")]["confidence"], "estimate")
        self.assertEqual(c[("154-1-10", "XT", "10")]["corrected"], "")  # ES-7 XT 1.222: may be genuine

    def test_closed_valve_xt_is_not_flagged(self):  # GX tables reach Cv 0 at 100%
        with open(ROOT / "data" / "flags.csv", encoding="utf-8") as fh:
            self.assertFalse(any(f["config_id"] == "219-1-1" and f["check"] == "out_of_range" for f in csv.DictReader(fh)))

    def test_applied_by_default_and_reversible(self):
        fixed = Catalog.load().get("70-1-5")
        printed = Catalog.load(corrections=False).get("70-1-5")
        self.assertEqual(fixed.curves["Cv"][20], 178)
        self.assertEqual(printed.curves["Cv"][20], 78)
        self.assertEqual(fixed.raw[("Cv", "20")], "078")
        self.assertEqual(fixed.corrections[("Cv", "20")]["confidence"], "high")
        est = Catalog.load(corrections="all").get("201-1-3")
        self.assertAlmostEqual(est.singles[("XT", "Coeffs. for 6 mm (0.25 Inch ) Travel(2)")], 0.53)

    def test_database(self):
        r = db.query("SELECT value, value_printed FROM v_flow_coefficient_corrected "
                     "WHERE config_id = '70-1-5' AND coefficient = 'Cv' AND position = 20")[0]
        self.assertEqual((r["value"], r["value_printed"]), (178, "078"))
        self.assertEqual(db.query("SELECT COUNT(*) n FROM catalog_correction")[0]["n"], len(corrections()))


if __name__ == "__main__":
    unittest.main()
