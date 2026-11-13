"""The worked examples printed in Fisher Catalog 12, Section 2, reproduced with fisher.sizing.

Each expected number is the one printed in the catalog. Where the catalog rounded an
intermediate value (e.g. Fp = 0.90) and carried the rounded value forward, the test does the same.
"""
import unittest

from fisher import sizing as s


class LiquidSampleProblem1(unittest.TestCase):
    """Page 2-8/2-9/2-10: liquid propane, 800 gpm, NPS 8 line, CL300 ES equal percentage cage."""

    def test_nps3_in_nps8_line(self):
        sk = s.sum_k(3, D_in=8, D_out=8)
        self.assertAlmostEqual(sk, 1.11, places=2)
        fp = s.fp(121, 3, sk)
        self.assertAlmostEqual(fp, 0.90, places=2)
        r = s.liquid_cv(800, 314.7, 289.7, 0.50, fp_value=0.90)
        self.assertAlmostEqual(r.cv, 125.7, places=1)

    def test_nps4_in_nps8_line(self):
        sk = s.sum_k(4, D_in=8, D_out=8)
        self.assertAlmostEqual(sk, 0.84, places=2)
        self.assertAlmostEqual(s.fp(203, 4, sk), 0.93, places=2)
        self.assertAlmostEqual(s.liquid_cv(800, 314.7, 289.7, 0.50, fp_value=0.93).cv, 121.7, places=1)
        fp = s.fp(121.7, 4, sk)
        self.assertAlmostEqual(fp, 0.97, places=2)
        self.assertAlmostEqual(s.liquid_cv(800, 314.7, 289.7, 0.50, fp_value=fp).cv, 116.2, places=1)


class LiquidSampleProblem2(unittest.TestCase):
    """Page 2-10: water, 2200 gpm, CL300 ED linear cage, choked (cavitating) flow."""

    def test_assumed_fl(self):
        self.assertAlmostEqual(s.dp_max_liquid(0.84, 389.7, 41.9, 0.90), 248.4, places=1)
        r = s.liquid_cv(2200, 389.7, 114.7, 0.93, fl=0.84, pv=41.9, ff_value=0.90)
        self.assertTrue(r.steps["choked"])
        self.assertAlmostEqual(r.cv, 134.6, places=1)

    def test_actual_fl(self):
        self.assertAlmostEqual(s.dp_max_liquid(0.82, 389.7, 41.9, 0.90), 236.7, places=1)
        r = s.liquid_cv(2200, 389.7, 114.7, 0.93, fl=0.82, pv=41.9, ff_value=0.90)
        self.assertAlmostEqual(r.cv, 137.9, places=1)


class LiquidSampleProblem3(unittest.TestCase):
    """Page 2-11: viscous lubricating oil, metric units, nonturbulent flow.

    The catalog's worked example prints N4 = 7600, but Table 2 gives 76000 for m3/h, and only
    76000 reproduces the printed Rev of 241.
    """

    def test_reynolds_and_cv(self):
        n1 = s.N["N1"]["m3/h,bar"]
        cvt = s.liquid_cv(300, 8.01, 6.01, 0.908, n1=n1).cv
        self.assertAlmostEqual(cvt, 234, delta=0.5)
        rev = s.reynolds(300, 8000, 0.68, 234, 80, fd=1.0, n4=s.N["N4"]["m3/h"], n2=s.N["N2"]["mm"])
        self.assertAlmostEqual(rev, 241, delta=0.5)
        # The catalog reads FR = 0.62 off the figure 3 curve; Table 3 interpolation gives 0.61.
        self.assertAlmostEqual(s.fr_from_reynolds(rev, "selection"), 0.61, delta=0.01)
        self.assertAlmostEqual(s.liquid_cv(300, 8.01, 6.01, 0.908, n1=n1, fr=0.62).cv, 377, delta=0.5)


class CompressibleSampleProblem1(unittest.TestCase):
    """Page 2-14/2-15: natural gas, 6.0e6 scfh, NPS 8 V250, choked.

    The catalog rounds Fk to 0.94 and Fk xT to three places; results agree within 0.5%.
    """

    def check(self, xt, printed):
        r = s.gas_cv(214.7, 64.7, 1.31, xt, q=6.0e6, gg=0.60, t1=520)
        self.assertTrue(r.steps["choked"])
        self.assertAlmostEqual(r.steps["Y"], 0.667, places=3)
        self.assertAlmostEqual(r.cv, printed, delta=printed * 0.005)

    def test_rated_xt(self):
        self.check(0.137, 1515)

    def test_xt_at_83_degrees(self):
        self.check(0.252, 1118)

    def test_xt_at_78_degrees(self):
        self.check(0.328, 980)


class CompressibleSampleProblem2(unittest.TestCase):
    """Page 2-15/2-16: superheated steam, 125,000 lb/h, NPS 4 ED in NPS 6 line."""

    def test_steam(self):
        sk = s.sum_k(4, D_in=6, D_out=6)
        self.assertAlmostEqual(sk, 0.463, places=3)
        fp = s.fp(236, 4, sk)
        self.assertAlmostEqual(fp, 0.95, places=2)
        k = s.reducer_k(4, 6)
        ki = k["K1"] + k["KB"]
        self.assertAlmostEqual(ki, 0.96, places=2)
        xtp = s.xtp(0.688, fp, 236, 4, ki)
        self.assertAlmostEqual(xtp, 0.67, places=2)
        r = s.gas_cv(514.7, 264.7, 1.28, xtp, w=125000, gamma1=1.0434, fp_value=fp)
        self.assertFalse(r.steps["choked"])
        self.assertAlmostEqual(r.steps["Y"], 0.73, delta=0.01)  # catalog rounds x, Fk, xTP first
        self.assertAlmostEqual(r.cv, 176, delta=176 * 0.01)


class Factors(unittest.TestCase):
    def test_fr_table_ends(self):
        self.assertEqual(s.fr_from_reynolds(50000), 1.0)
        self.assertAlmostEqual(s.fr_from_reynolds(56), 0.284)
        self.assertAlmostEqual(s.fr_from_reynolds(10, "selection"), 0.019 * 10 ** 0.67)

    def test_expansion_factor_limit(self):
        y, x_used, choked = s.expansion_factor(0.9, 1.0, 0.5)
        self.assertTrue(choked)
        self.assertAlmostEqual(y, 2 / 3)
        self.assertEqual(x_used, 0.5)

    def test_ff(self):
        self.assertAlmostEqual(s.ff(0, 3206.2), 0.96)

    def test_kv(self):
        self.assertAlmostEqual(s.Result(100).kv, 86.5)


if __name__ == "__main__":
    unittest.main()


class MetricGas(unittest.TestCase):
    """Catalog 12 Table 2 metric N6-N9 constants give the same Cv as US units (to constant rounding)."""

    def test_units_agree(self):
        from fisher import sizing
        us = sizing.gas_cv(214.7, 64.7, 1.31, 0.137, q=6e6, gg=0.6, t1=520).cv
        kpa = sizing.gas_cv(214.7 * 6.89476, 64.7 * 6.89476, 1.31, 0.137, q=6e6 * 0.0283168, gg=0.6, t1=520 / 1.8,
                            units="kpa").cv
        bar = sizing.gas_cv(214.7 * 0.0689476, 64.7 * 0.0689476, 1.31, 0.137, q=6e6 * 0.0283168, gg=0.6,
                            t1=520 / 1.8, units="bar").cv
        self.assertAlmostEqual(kpa / us, 1, delta=0.005)
        self.assertAlmostEqual(bar, kpa, delta=1e-6)
        w_us = sizing.gas_cv(214.7, 64.7, 1.31, 0.137, w=1000, gamma1=0.5).cv
        w_m = sizing.gas_cv(214.7 * 6.89476, 64.7 * 6.89476, 1.31, 0.137, w=453.592, gamma1=0.5 * 16.0185,
                            units="kpa").cv
        self.assertAlmostEqual(w_m / w_us, 1, delta=0.005)
