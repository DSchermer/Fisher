"""Catalog 14 torque method for every rotary valve (section D), from the typed factors."""
import unittest

from fisher import torque


class TorqueAllValves(unittest.TestCase):
    def test_every_valve_with_tables(self):
        self.assertEqual(len(torque.valves()), 26)
        for v in ("8532", "8560", "8580", "8590", "9500", "A11", "A31A", "A31D", "CV500", "Control-Disk",
                  "V150/V200/V300", "V250", "V260", "V270", "V280", "V500", "Z500", "SIS"):
            self.assertIn(v, torque.valves())

    def test_v300_attenuator_sample_calculation(self):  # pages D-113 / D-114
        km = dict(zip(range(10, 100, 10), [0.76, 0.64, 0.69, 0.61, 0.62, 0.51, 0.53, 0.47, 0.40]))
        actual = {10: 400, 20: 350, 30: 250, 40: 150, 50: 100, 60: 70, 70: 50, 80: 40, 90: 30}
        (r,) = torque.valve_torque_catalog("V150/V200/V300", 12, variant="with Attenuator", dp_shutoff=440,
                                           p1_psig=440, fluid="gas", k=km, actual_dp=actual)
        self.assertEqual(r.breakout_lbf_in, 4760)  # 4 (440) + 3000
        printed = {30: 14750, 40: 16950, 50: 15400, 60: 15120, 70: 13250, 80: 12800, 90: 9960}
        for angle, td in printed.items():
            self.assertAlmostEqual(r.dynamic_lbf_in[angle], td, delta=1)
        self.assertAlmostEqual(r.dynamic_lbf_in[20], 7250, delta=0.005 * 7250)  # catalog rounds dP eff to 290
        self.assertEqual(r.mast_lbf_in, 12000)  # spline limit
        self.assertFalse(r.within_mast)  # "a different valve size or style must be selected"

    def test_8532_reverse_flow_row(self):  # page D-13, NPS 14
        (o,) = torque.options("8532", 14, flow="reverse", pressure_class="CL150", construction="Soft Seal")
        self.assertEqual(o.a, {"": 12.15})
        self.assertEqual(o.b, {"PTFE": 1499, "UHMWPE": 2838})
        self.assertEqual(o.c[75], 24)
        self.assertEqual(o.direction[75], "tends to open")  # the theta mark
        self.assertEqual(o.mast, {"": 11388})

    def test_7600_agrees_with_typed_table(self):
        for row in torque.torque_characteristics():
            opts = [o for o in torque.options("7600", row["nps"]) if row["shaft_in"] in o.shaft]
            hit = [o for o in opts if abs(o.a.get("", -1) - float(row["A"])) < 1e-9 and o.b.get("") == float(row["B"])
                   and o.c.get(60) == float(row["C_60"]) and o.mast.get("") == float(row["max_torque_lbf_in"])]
            self.assertTrue(hit, row)

    def test_k_values_by_class(self):  # page D-10
        self.assertEqual(torque.k_values("8532", 14, pressure_class="CL150"),
                         {"CL150 | page D-10 table 1": {10: 0.227, 60: 0.203, 75: 0.155, 80: 0.136, 90: 0.103}})
        self.assertEqual(torque.k_values("8532", 20, pressure_class="CL300")["CL300 | page D-10 table 2"][60], 0.181)

    def test_liquid_effective_dp(self):  # page D-10: FL^2 (P1abs - FF Pv)
        self.assertAlmostEqual(torque.effective_dp_liquid(100, 0.6, 0.94, 0.5), 0.36 * (114.7 - 0.47))

    def test_shaft_strength(self):  # page D-6, Table 3
        s = torque.shaft_strength("7600")
        self.assertIn({"material": "S17400 (17-4PH H1075 stainless steel)", "temperature_f": "101 to 200",
                       "percent": 57.0, "source": "Fisher Catalog 14, page D-6"}, s)

    def test_conservative_choice_is_noted(self):
        res = torque.valve_torque_catalog("8532", 14, flow="reverse", pressure_class="CL150", construction="Soft Seal",
                                          dp_shutoff=100, p1_psig=100, fluid="liquid", fl=0.6, ff=0.94, pv_psia=0.5)
        self.assertEqual(res[0].breakout_lbf_in, 12.15 * 100 + 2838)
        self.assertTrue(any("largest" in n for n in res[0].notes))
        res = torque.valve_torque_catalog("8532", 14, flow="reverse", pressure_class="CL150", construction="Soft Seal",
                                          dp_shutoff=100, p1_psig=100, fluid="liquid", fl=0.6, ff=0.94, pv_psia=0.5,
                                          b_key="PTFE")
        self.assertEqual(res[0].breakout_lbf_in, 12.15 * 100 + 1499)


if __name__ == "__main__":
    unittest.main()
