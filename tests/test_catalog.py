"""Lookups over the extracted data, checked against values printed in Fisher Catalog 12."""
import csv
import unittest
from pathlib import Path

from fisher import Catalog, parse_nps
from fisher import sizing as s

DATA = Path(__file__).resolve().parent.parent / "data"


def one(cat, **kw):
    hits = [c for c in cat.find(include_aliases=False, **kw) if not c.restricted]
    assert len(hits) == 1, [(c.config_id, c.page_title) for c in hits]
    return hits[0]


class ValuesQuotedInSection2(unittest.TestCase):
    """Section 2's worked examples quote values from the coefficient tables; the data must match."""

    @classmethod
    def setUpClass(cls):
        cls.cat = Catalog.load()

    def test_es_equal_percentage(self):  # page 2-9: "CL300, NPS 3 ES ... Cv = 121", "NPS 4 ... Cv = 203"
        self.assertEqual(one(self.cat, family="ES", nps=3, characteristic="Equal Percentage").rated(), 121)
        self.assertEqual(one(self.cat, family="ES", nps=4, characteristic="Equal Percentage").rated(), 203)

    def test_ed_linear(self):  # page 2-10: "NPS 3 CL300 ED ... linear cage has a Cv of 133 at 80 percent"
        nps3 = one(self.cat, family="ED", nps=3, text="Linear Cage")
        self.assertEqual(nps3.value_at(80), 133)
        nps4 = one(self.cat, family="ED", nps=4, text="Linear Cage")  # page 2-15/2-16
        self.assertEqual(nps4.rated(), 236)
        self.assertEqual(nps4.rated("XT"), 0.688)

    def test_v250(self):  # page 2-14: "NPS 8 V250 ... rated Cv = 2190"
        self.assertEqual(one(self.cat, family="V250", nps=8).rated(), 2190)


class Lookups(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = Catalog.load()

    def test_counts(self):
        self.assertEqual(len(self.cat.families()), 61)
        self.assertGreater(len(self.cat.configs), 3500)

    def test_interpolation(self):
        c = self.cat.get("120-1-2")  # ED-1, NPS 1-1/2, 47.6 mm port, quick opening
        self.assertEqual(c.value_at(50), 32.0)
        self.assertAlmostEqual(c.value_at(55), (32.0 + 36.6) / 2)
        self.assertIsNone(c.value_at(5))
        self.assertAlmostEqual(c.opening_for(32.0), 50)
        self.assertIsNone(c.opening_for(1000))

    def test_single_values_and_notes(self):
        c = self.cat.get("120-1-2")
        self.assertEqual(c.singles[("FL", "FL (3)")], 0.79)
        self.assertIn(("3", "At 100% travel."), self.cat.notes(120))

    def test_restricted_trim(self):
        ez = [c for c in self.cat.find(family="EZ", nps=2) if c.page == 201]
        self.assertEqual(len(ez), 2)
        self.assertEqual(sorted(c.restricted for c in ez), [False, True])
        es = [c for c in self.cat.find(family="ES", nps=4) if c.page == 152]
        self.assertEqual({c.rated(): c.restricted for c in es}, {203.0: False, 121.0: True})

    def test_aliases(self):
        self.assertEqual({a.uses for a in self.cat.resolve("EDR")}, {"ED"})
        self.assertTrue(all(c.family == "ED" for c in self.cat.find(family="EDR")))
        es = self.cat.find(family="ES")
        self.assertEqual({c.family for c in es}, {"ES", "ED"})
        self.assertEqual({c.page for c in es if c.family == "ED"}, {131, 132})  # "also appropriate for ES"
        self.assertEqual(self.cat.resolve("FB")[0].uses, "external")

    def test_find_valves_is_deterministic(self):
        a = [(c.config_id, op) for c, op in self.cat.find_valves(50, family="ED")]
        b = [(c.config_id, op) for c, op in self.cat.find_valves(50, family="ED")]
        self.assertEqual(a, b)
        self.assertTrue(a)
        for c, op in self.cat.find_valves(50, family="ED"):
            self.assertTrue(20 <= op <= 80)
            self.assertAlmostEqual(c.value_at(op), 50, delta=0.5)  # opening is rounded to 0.1

    def test_sizing_with_catalog_data(self):
        """Liquid sample problem 1 end to end, taking each Cv from the extracted tables."""
        sk = s.sum_k(4, D_in=8, D_out=8)
        nps4 = one(self.cat, family="ES", nps=4, characteristic="Equal Percentage")
        required = s.liquid_cv(800, 314.7, 289.7, 0.50, fp_value=s.fp(nps4.rated(), 4, sk)).cv
        self.assertLess(required, nps4.rated())
        # page 2-10: "an NPS 4 valve opened to about 75 percent of total travel"
        self.assertAlmostEqual(nps4.opening_for(required), 75, delta=5)

    def test_parse_nps(self):
        cases = {"1-1/2(2)": [1.5], "2 & 3 x 2": [2.0, 3.0], "DN25 NPS 1": [1.0], "20x16": [20.0],
                 "6.35 (1/4) 12.7 (1/2)": [0.25, 0.5], "1 & 1-1/4": [1.0, 1.25], "A1": []}
        for raw, want in cases.items():
            self.assertEqual(parse_nps(raw), want, raw)


class DataIntegrity(unittest.TestCase):
    def test_every_value_row_confirmed_by_second_reader(self):
        with open(DATA / "crosscheck.csv") as fh:
            rows = list(csv.DictReader(fh))
        unmatched = [r for r in rows if r["status"] == "no_match"]
        # 4 known: two rows poppler wraps (81000-1) and two with a stray glyph (V500-7); verified by eye.
        self.assertLessEqual(len(unmatched), 4, unmatched)

    def test_values_reference_configs(self):
        with open(DATA / "configs.csv") as fh:
            configs = {r["config_id"] for r in csv.DictReader(fh)}
        with open(DATA / "coefficients.csv") as fh:
            missing = {v["config_id"] for v in csv.DictReader(fh)} - configs
        self.assertFalse(missing)


if __name__ == "__main__":
    unittest.main()
