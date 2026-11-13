"""Flow and pressure-drop prediction, velocity, two-phase sizing, and sizing on a specific catalog valve."""
import unittest

from fisher import Catalog
from fisher import sizing as s
from fisher.select import size_gas_on_valve, size_liquid_on_valve


class Prediction(unittest.TestCase):
    def test_liquid_flow_is_inverse_of_sizing(self):
        r = s.liquid_cv(2200, 389.7, 114.7, 0.93, fl=0.84, pv=41.9, ff_value=0.90)
        q = s.predict_liquid_flow(r.cv, 389.7, 114.7, 0.93, fl=0.84, pv=41.9, ff_value=0.90)
        self.assertAlmostEqual(q.value, 2200, places=6)
        self.assertTrue(q.steps["choked"])

    def test_liquid_dp_is_inverse_of_sizing(self):
        cv = s.liquid_cv(800, 314.7, 289.7, 0.50, fp_value=0.93).cv
        self.assertAlmostEqual(s.predict_liquid_dp(800, cv, 0.50, fp_value=0.93).value, 25, places=6)

    def test_viscous_flow_uses_flow_column(self):
        # Liquid sample problem 3 (page 2-11): 80 mm V100, Cv 372, FL 0.68, oil at 8000 cSt, 2 bar.
        q = s.predict_liquid_flow(372, 8.01, 6.01, 0.908, n1=s.N["N1"]["m3/h,bar"], fl=0.68, nu=8000, d=80,
                                  n2=s.N["N2"]["mm"], n4=s.N["N4"]["m3/h"])
        self.assertLess(q.steps["FR"], 1.0)
        self.assertAlmostEqual(q.value, q.steps["FR"] * q.steps["q_turbulent"])

    def test_gas_flow_is_inverse_of_sizing(self):
        q = s.predict_gas_flow(1515, 214.7, 64.7, 1.31, 0.137, gg=0.6, t1=520)
        self.assertAlmostEqual(q.value / 6.0e6, 1, delta=0.005)  # catalog's rounded Fk gives Cv 1515
        w = s.predict_gas_flow(176, 514.7, 264.7, 1.28, 0.6666, gamma1=1.0434, fp_value=0.9478, mass=True)
        self.assertAlmostEqual(w.value / 125000, 1, delta=0.01)


class Velocity(unittest.TestCase):
    def test_sonic_velocity_air(self):
        self.assertAlmostEqual(s.sonic_velocity(1.40, 28.97, 520), 1118, delta=1)

    def test_steam_velocity(self):
        self.assertAlmostEqual(s.steam_velocity(10000, 5.0, 20), 100.0)

    def test_mach(self):
        m1 = s.mach_inlet(1.4, 1000, 12.73, 35, 50, 100)
        m2 = s.mach_outlet(1.4, m1, 12.73, 12.73, 50, 100)
        self.assertGreater(m2, m1)  # gas expands through the valve: outlet faster for equal areas


class Mixtures(unittest.TestCase):
    """Page 2-31/2-32 sizing examples. Fm is read off figure 1 in the catalog; the printed value is used."""

    def test_liquid_gas(self):
        self.assertAlmostEqual(s.gas_volume_ratio_gas(625000, 3000, 414.7, 560), 0.498, places=3)
        self.assertAlmostEqual(s.mixture_dp_allow(0.40, 414.7, 0.84, 30), 156, delta=0.5)
        r = s.mixture_cv(581, 2710, 24.7, 0.475)
        self.assertAlmostEqual(r.steps["Cvg"], 110, delta=0.5)
        self.assertAlmostEqual(r.cv, 1020, delta=2)

    def test_wet_steam(self):
        self.assertAlmostEqual(s.gas_volume_ratio_vapor(5.185, 0.0176, 0.05), 0.939, places=3)
        self.assertAlmostEqual(s.mixture_dp_allow(0.50, 84.7, 0.92, 84.7), 3.39, places=2)
        self.assertAlmostEqual(s.mixture_cv(216, 2330, 21.0, 0.97).steps["Cvg"], 111, delta=0.5)


class TwoPhaseCharts(unittest.TestCase):
    def test_fm_against_examples(self):  # page 2-31/2-32 readings, within chart-reading accuracy
        from fisher import reference as ref
        self.assertAlmostEqual(ref.two_phase_fm(0.498), 0.475, delta=0.025)
        self.assertAlmostEqual(ref.two_phase_fm(0.939), 0.97, delta=0.02)
        self.assertAlmostEqual(ref.critical_gas_dp_ratio(24.7), 0.40, delta=0.02)  # example 1, step 1

    def test_end_to_end_liquid_gas(self):
        from fisher import reference as ref
        vr = s.gas_volume_ratio_gas(625000, 3000, 414.7, 560)
        r = s.mixture_cv(581, 2710, 24.7, ref.two_phase_fm(vr))
        self.assertAlmostEqual(r.cv, 1020, delta=1020 * 0.02)


class SizingOnCatalogValve(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = Catalog.load()

    def test_gas_sample_problem_1_iteration(self):
        """Page 2-14/2-15: sized with rated xT the valve sits near 83 degrees; re-reading xT moves it to
        about 78 and then "approximately 75 degrees". The loop reproduces those steps, then converges."""
        v = self.cat.find(family="V250", nps=8)[0]
        r = size_gas_on_valve(v, 214.7, 64.7, 1.31, q=6.0e6, gg=0.6, t1=520)
        ops = [it["opening"] for it in r.iterations]
        self.assertAlmostEqual(ops[0], 83, delta=1)
        self.assertAlmostEqual(ops[1], 78, delta=1)
        self.assertAlmostEqual(ops[2], 75, delta=1)
        self.assertTrue(70 < r.opening < 75)

    def test_liquid_sample_problem_2(self):
        """Page 2-10: NPS 3 CL300 ED linear cage with actual FL 0.82 -> Cv 137.9, about 85 percent open."""
        v = [c for c in self.cat.find(family="ED", nps=3, text="Linear Cage", include_aliases=False)
             if not c.restricted][0]
        r = size_liquid_on_valve(v, 2200, 389.7, 114.7, 0.93, pv=41.9, ff_value=0.90)
        self.assertAlmostEqual(r.required_cv, 137.9, places=1)
        self.assertAlmostEqual(r.opening, 85, delta=1)

    def test_too_small(self):
        v = self.cat.find(family="V250", nps=8)[0]
        self.assertIsNone(size_gas_on_valve(v, 214.7, 64.7, 1.31, q=6.0e7, gg=0.6, t1=520).opening)


if __name__ == "__main__":
    unittest.main()
