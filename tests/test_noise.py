"""Section 3 hydrodynamic noise: the page 3-7 prediction example and the chart fits."""
import unittest

from fisher import noise as n


class PredictionExample(unittest.TestCase):
    """Page 3-7: Fisher ED, standard trim, NPS 4 sch 40, Km 0.7, P1 250 psia, dP 175 psi, Pv 11.5, Cv 70.

    The catalog reads each term off its chart to the nearest dB; terms from the fitted charts are
    compared within the reading resolution. Its non-cavitating SPL_dP of 81 reads about 1 dB high
    against the drawn line (79.9), so totals agree within 1.5 dB.
    """

    def setUp(self):
        self.r = n.hydrodynamic_noise(dp=175, p1=250, pv=11.5, cv=70, km=0.7, nps=4, schedule=40)

    def test_terms(self):
        nc, cav = self.r.non_cavitating, self.r.cavitating
        self.assertEqual(nc["dSPL_K"], -32.9)                         # table, exact
        self.assertAlmostEqual(cav["dSPL_Ar"], -8, delta=0.1)         # equation, exact (-7.94)
        self.assertAlmostEqual(cav["SPL_dP"], 107, delta=0.5)
        self.assertAlmostEqual(nc["SPL_dP"], 81, delta=1.2)
        self.assertAlmostEqual(nc["dSPL_Cv"], 18, delta=0.5)
        self.assertAlmostEqual(nc["dSPL_Km"], 0.7, delta=0.2)
        self.assertEqual(nc["dSPL_G"], 0)

    def test_totals(self):
        self.assertAlmostEqual(self.r.non_cavitating["SPL"], 66.8, delta=1.5)
        self.assertAlmostEqual(self.r.cavitating["SPL"], 84.1, delta=1.5)
        self.assertEqual(self.r.governing, "cavitating")
        self.assertAlmostEqual(self.r.spl_dba, 84.1, delta=1.5)


class Terms(unittest.TestCase):
    def test_chart_ranges(self):
        with self.assertRaises(ValueError):
            n.dspl_g(5)
        with self.assertRaises(ValueError):
            n.spl_dp(20000, True)

    def test_ar_styles(self):  # page 3-1 coefficients
        self.assertAlmostEqual(n.dspl_ar(0.5, 0.5, "standard") - n.dspl_ar(0.5, 0.5, "cavitrol_iii_1_stage"), 5.0)

    def test_cap(self):
        r = n.hydrodynamic_noise(dp=1000, p1=1100, pv=1, cv=500, km=0.5, nps=4, schedule=40, style="cavitrol_iv")
        self.assertEqual(r.spl_dba, 90.0)

    def test_k_table(self):
        self.assertEqual(n.dspl_k("1-1/2", "XXS"), -54.3)
        with self.assertRaises(KeyError):
            n.dspl_k(36, 40)


if __name__ == "__main__":
    unittest.main()
