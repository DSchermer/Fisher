"""Catalog 14 force method: 585C spring-biased, 685, 685SE/SR, 785C, 3025, 657C actuators and stem load."""
import unittest

from fisher import actuator_force as af
from fisher import piston_actuators as p
from fisher import stem_load as s


class PistonActuators(unittest.TestCase):
    def test_585c_spring_table(self):  # page B-21
        t = p.spring_table_585c()
        hit = [r for r in t if r["size"] == "50" and r["rate_lb_in"] == 1550 and r["travel_in"] == 2]
        self.assertEqual(hit[0]["force_lb"], 4650)
        self.assertEqual(len(t), 55)

    def test_585c_fail_open_logic(self):  # pages B-19/B-20: lightest passing spring per size
        res = p.select_585c_spring_biased(a=300, b=500, c=200, travel_in=0.75, supply_psig=60, fail="open",
                                          pressure_tends_to="open")
        first = next(r for r in res if r.size == "25" and r.passes)
        self.assertEqual(first.values["rate_lb_in"], 200)  # 350 lb at 0.75 in >= C + D - A = -100; 200 >= C
        self.assertEqual(first.values["air_force_lb"], 60 * 26.0)
        # a heavier spring leaves too little air force to seat: 60 x 26 - 700 < A + B + C
        self.assertFalse(next(r for r in res if r.size == "25" and r.values["rate_lb_in"] == 400).passes)

    def test_685_table_a(self):  # page B-26
        r = next(x for x in p.table_685() if x["size"] == "20" and x["stroke"] == "push")
        self.assertEqual((r["force_100psig_lb"], r["max_cylinder_psig"]), (31416, 150))
        sel = p.select_685(15000, 80)
        self.assertEqual(next(c for c in sel if c.passes).size, "16")  # 20106 x 0.8 = 16085

    def test_685s_tables(self):  # pages B-27.5 to B-27.7
        self.assertEqual(p.table_685s()["20"], {"piston_in2": 314.0, "rod_in2": 7.07})
        self.assertEqual(p.springs_685s()[0], (50, 500))
        self.assertEqual(len(p.springs_685s()), 40)
        self.assertEqual(p.plug_weight(8), 90)
        self.assertEqual(p.plug_weight(8, fb=True), 140)
        self.assertEqual(p.motl("28", "685SR"), 143200)
        self.assertEqual(p.tac(4), 4.5)  # (4 + 0.25) rounded up to the nearest 0.5

    def test_685se_equations(self):  # page B-27.1 / B-27.2
        (r,) = p.size_685s("685SE", a=2000, b=3000, c=500, port_circumference_in=25.13, port_in=8, travel_in=4,
                           supply_psig=80, pressure_tends_to="open", sizes=["14"])
        pa, pl, ks, t = 154.0, r.values["preload_lb"], r.values["ks_lb_in"], 4.5
        self.assertAlmostEqual(r.values["required_spring_thrust_lb"], 2000 + min(40 * 25.13, 3000) + 500 + 2 * pa)
        self.assertGreaterEqual(pl, r.values["required_spring_thrust_lb"])
        self.assertAlmostEqual(r.values["actuator_thrust_down_lb"], 80 * pa + pl - 2 * pa)
        self.assertAlmostEqual(r.values["actuator_thrust_up_lb"], 80 * (pa - 4.91) - pl * 1.1 - 1.05 * ks * t - 2 * pa)
        self.assertGreaterEqual(r.values["bench_set_psi"], 5)
        self.assertTrue(r.passes)

    def test_785c(self):  # page B-27.8
        t = p.table_785c()["335"]
        self.assertEqual((t["piston_in2"], t["max_thrust_lb"]), (136.62, 20493))
        sel = p.select_785c(12000, 100)
        self.assertEqual(next(c for c in sel if c.passes).size, "335")  # 280: 9544 < 12000; 335: 13662

    def test_3025(self):  # page B-76: P900 air-to-close at 3 in travel and 4 bar = 12770 lb
        hits = p.select_3025(12000, 3, action="air-to-close", supply_bar=4)
        self.assertIn(("P900", 12770.0), [(h["size"], h["thrust_lb"]) for h in hits])
        self.assertEqual(len(p.table_3025()), 119)

    def test_657c_in_diaphragm_selection(self):  # page B-46.2: size 46i, 0-18 psig, 1.78 in: 780 lb (5-15)
        hits = af.select_diaphragm(700, 1.78, actuator="657C", supply="0-18")
        self.assertIn(("46i", 780.0, "5-15"), [(h["size"], h["force_lb"], h["bench_set"]) for h in hits])


class StemLoad(unittest.TestCase):  # page B-99 worked example: CL300 NPS 6 ED, 3/4 in 316 SH stem
    def test_usage_guide(self):
        self.assertEqual([r["tables"] for r in s.tables_for("ED", bonnet="Plain")], ["3 & 4"])

    def test_316_strain_hardened(self):
        self.assertEqual(s.max_stem_load(0.75, 400).max_stem_load_lb, 7980)
        self.assertAlmostEqual(s.max_stem_load(0.75, 750).max_stem_load_lb, 6810, delta=10)  # catalog: 6810

    def test_other_material(self):
        r = s.max_stem_load(0.75, 400, material="17-4PH")
        self.assertAlmostEqual(r.max_stem_load_lb, 10100, delta=10)  # 5060 x 1.997

    def test_check(self):
        self.assertFalse(s.check(9000, 0.75, 400)["within_limit"])
        self.assertTrue(s.check(9000, 0.75, 400, material="17-4PH")["within_limit"])

    def test_per_valve_tables(self):
        self.assertEqual(float(s.valve_stem_loads("HPT-C")[0]["max_stem_load_lb"]), 10803)


if __name__ == "__main__":
    unittest.main()
