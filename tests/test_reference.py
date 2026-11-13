"""Section 2 reference tables, checked against values printed in the catalog."""
import csv
import unittest

from fisher import reference as ref


class Steam(unittest.TestCase):
    def test_table_rows(self):  # page 2-33: 40.0 psia -> 267.25 F, .0953 lb/ft3, SG .94
        s = ref.saturated_steam(psia=40.0)
        self.assertAlmostEqual(s["temp_f"], 267.25)
        self.assertAlmostEqual(s["steam_density_lb_ft3"], 0.0953)
        self.assertAlmostEqual(s["water_specific_gravity"], 0.94)
        self.assertIn("2-33", s["source"])

    def test_critical_point(self):  # page 2-34 last row
        self.assertAlmostEqual(ref.saturated_steam(psia=3206.2)["temp_f"], 705.4)

    def test_interpolation_and_inverse(self):
        t = ref.saturated_steam(psia=40.5)["temp_f"]
        self.assertTrue(267.25 < t < 268.74)
        self.assertAlmostEqual(ref.saturated_steam(temp_f=267.25)["psia"], 40.0)

    def test_monotonic(self):
        with open(ref.REF_DIR / "saturated_steam.csv") as fh:
            rows = [(float(r["psia"]), float(r["temp_f"])) for r in csv.DictReader(fh)]
        self.assertEqual(len(rows), 285)
        self.assertTrue(all(b[0] > a[0] and b[1] > a[1] for a, b in zip(rows, rows[1:])))

    def test_out_of_range(self):
        with self.assertRaises(ValueError):
            ref.saturated_steam(psia=5000)


class Tables(unittest.TestCase):
    def test_k_values(self):  # page 2-37 Table 1
        self.assertEqual(ref.specific_heat_ratio("Air"), 1.40)
        self.assertEqual(ref.specific_heat_ratio("argon"), 1.67)

    def test_pipe_area(self):  # page 2-40 Table 11
        self.assertEqual(ref.pipe_flow_area("1/2", 40), 0.30)
        self.assertEqual(ref.pipe_flow_area("1-1/2", 80), 1.8)
        self.assertIsNone(ref.pipe_flow_area("1/2", 10))

    def test_all_rows_confirmed_by_second_reader(self):
        # Exceptions checked by hand: Table 13 (formulas, not numbers), Table 14 (verified F/C pairs
        # by formula below), EH Table 6 (first row's size label wraps over three lines).
        for t in ref.tables():
            if t["title"].startswith(("Table 13. Temperature", "Table 14. Abbreviated", "Table 6. Fisher EH")):
                continue
            self.assertEqual(t["rows"], t["rows_confirmed"], t["title"])

    def test_temperature_pairs(self):
        _, rows = ref.table("Abbreviated Conversions of Degrees")
        n = 0
        for r in rows:
            for i in range(0, len(r), 2):
                if r[i] and r[i + 1]:
                    self.assertAlmostEqual((float(r[i]) - 32) * 5 / 9, float(r[i + 1]), delta=0.6)
                    n += 1
        self.assertGreater(n, 130)

    def test_leakage(self):  # page 2-28
        self.assertAlmostEqual(ref.allowable_leakage("IV", rated_cv=236)["leakage_cv"], 0.0236)
        self.assertAlmostEqual(ref.allowable_leakage("V", dp_psi=100, port_diameter_in=2)["ml_per_min"], 0.1)
        self.assertEqual(ref.allowable_leakage("Class VI", port_diameter_in="1-1/2")["ml_per_min"], 0.30)
        self.assertEqual(ref.allowable_leakage("VI", port_diameter_in=4)["bubbles_per_min"], 11)


if __name__ == "__main__":
    unittest.main()
