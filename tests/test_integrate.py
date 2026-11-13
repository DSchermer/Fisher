"""Linking Catalog 12 valve configurations to Catalog 14 actuator ratings."""
import csv
import unittest
from pathlib import Path

from fisher import Catalog
from fisher import integrate as I

LINKS = Path(__file__).resolve().parent.parent / "data" / "links" / "catalog12_to_catalog14.csv"


class Links(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = Catalog.load()

    def test_sliding_stem_es(self):
        """ES NPS 3, equal percentage cage (ES-5): 3.4375 inch port, 1.5 inch travel, unbalanced.
        Catalog 14 page A-3, 3.4375 inch port, 585C: size 60 = 214/267/375/483, size 68 = 374/460 psi."""
        m = I.actuators_for_config(self.cat.get("152-1-8"))
        self.assertEqual((m.matched_on["port_in"], m.matched_on["travel_in"], m.matched_on["balance"]),
                         (3.4375, 1.5, "Unbalanced"))
        a3 = sorted(r.value for r in m.ratings if r.printed_label == "A-3" and r.actuator == "585C")
        self.assertEqual(a3, [214, 267, 374, 375, 460, 483])
        self.assertEqual(sorted(r.value for r in I.actuators_for_config(self.cat.get("152-1-8"), 300).ratings
                                if r.printed_label == "A-3"), [374, 375, 460, 483])

    def test_fractional_port(self):  # D, Micro-Form: port "1/4" inch, travel "3/4" inch
        m = I.actuators_for_config(self.cat.get("92-1-1"))
        self.assertEqual((m.matched_on["port_in"], m.matched_on["travel_in"]), (0.25, 0.75))
        self.assertTrue(m.ratings)

    def test_rotary(self):
        v150 = self.cat.find(family="V150", nps=4)[0]
        m = I.actuators_for_config(v150, 200, angle_deg=0)
        self.assertTrue(m.ratings)
        self.assertTrue(all("V150" in r.valve and r.valve_nps == 4 and r.angle_deg == 0 and r.value >= 200
                            for r in m.ratings))

    def test_dn_sizes(self):  # the 8580 table in Catalog 12 prints DN sizes
        sizes = sorted({s for c in self.cat.configs.values() if c.family == "8580" for s in c.sizes})
        self.assertEqual(sizes, [2, 3, 4, 6, 8, 10, 12])
        self.assertTrue(I.actuators_for_config(self.cat.find(family="8580", nps=4)[0]).ratings)

    def test_not_covered_says_why(self):
        m = I.actuators_for_config(self.cat.get("5-1-1"))  # Fisher 461
        self.assertFalse(m.ratings)
        self.assertIn("force method", m.note)

    def test_link_table(self):
        with open(LINKS, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(sum(1 for r in rows if r["ratings"] != "0"), 470)
        self.assertTrue(all(r["note"] for r in rows if r["ratings"] == "0"))


if __name__ == "__main__":
    unittest.main()
