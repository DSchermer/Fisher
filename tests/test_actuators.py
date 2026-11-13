"""Catalog 14 actuator selection, checked against values printed in the catalog."""
import csv
import unittest

from fisher import actuators as a


class PrintedValues(unittest.TestCase):
    def find(self, **kw):
        return [r for r in a.ratings() if all(getattr(r, k) == v for k, v in kw.items())]

    def test_sliding_stem_585c(self):  # page A-3, 1 inch port, travel 1.125, size 60
        rs = self.find(printed_label="A-3", port_in=1.0, travel_in=1.125, actuator_size="60")
        self.assertEqual([r.value for r in rs], [2925, 3562, 4834, 6000])
        self.assertTrue(rs[0].column.endswith("50"))
        self.assertEqual((rs[0].leakage, rs[0].balance), ("Class IV", "Unbalanced"))

    def test_rotary_8532(self):  # page C-26: 8532 NPS 14 with 1052 size 70 at 33 psig
        rs = [r for r in self.find(printed_label="C-26", valve_nps=14.0) if r.column.startswith("33 Psig")]
        self.assertEqual({r.angle_deg: r.value for r in rs}, {0: 201, 60: 10, 90: 1})
        self.assertEqual(rs[0].actuator, "1052")

    def test_rotary_v150(self):  # page C-130: V150 NPS 1 at 0 degrees, size 30, 60 psig
        r = [r for r in self.find(printed_label="C-130", valve_nps=1.0, angle_deg=0.0)
             if r.column.endswith("Size 30 › 60 psig")]
        self.assertEqual(r[0].value, 740)

    def test_wrapped_label(self):  # page C-39: liner printed as "Nitrile / or / PTFE"
        liners = {r.keys.get("Liner Material") for r in self.find(printed_label="C-39")}
        self.assertIn("Nitrile or PTFE", liners)
        self.assertNotIn("or", liners)

    def test_every_value_confirmed_by_second_reader(self):
        with open(a.C14_DIR / "allowable_dp.csv", encoding="utf-8") as fh:
            rows = [r for r in csv.DictReader(fh) if r["value"]]
        self.assertGreater(len(rows), 21000)
        self.assertTrue(all(r["confirmed"] == "1" for r in rows))


class Selection(unittest.TestCase):
    def test_sliding_stem(self):
        rs = a.sliding_stem(500, 2.5, actuator="585C")
        self.assertTrue(rs)
        self.assertTrue(all(r.value >= 500 and r.port_in == 2.5 for r in rs))
        sizes = [int(r.actuator_size.split("(")[0]) for r in rs]
        self.assertEqual(sizes, sorted(sizes))  # smallest actuator first

    def test_rotary(self):
        rs = a.rotary(200, "V150", 4, angle_deg=0)
        self.assertTrue(rs and all(r.valve.startswith("V150") and r.valve_nps == 4 and r.value >= 200 for r in rs))

    def test_rotary_by_shaft(self):
        self.assertTrue(a.rotary(100, "CV500", shaft_in="1-1/2"))

    def test_tables(self):
        self.assertGreater(len(a.tables()), 600)
        hits = a.search_tables("Port Data", "B")
        headers, rows = a.table(hits[0]["id"])
        self.assertTrue(rows)


if __name__ == "__main__":
    unittest.main()
