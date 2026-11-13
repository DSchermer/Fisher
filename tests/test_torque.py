"""Catalog 14 torque method (section D)."""
import unittest

from fisher import torque as T


class TorqueMethod(unittest.TestCase):
    def test_three_way_butterfly_example(self):
        """Page D-100: dP shutoff 100 psi, actual dP at 60 deg 7 psi, P1 10 psig, A 0.400, B 36, C 19.8:
        TB = 76 lbf-in; dP_eff = 0.600 x 24.7 = 14.8 > 7, so 7 is used; TD = 139 lbf-in."""
        r = T.valve_torque(a=0.400, b=36, c=19.8, dp_shutoff=100, p1_psig=10, dp_eff_factor=0.600, actual_dp=7.0)
        self.assertEqual(r.breakout_lbf_in, 76)
        self.assertEqual(r.dp_eff, 7.0)
        self.assertAlmostEqual(r.dynamic_lbf_in, 139, delta=0.5)
        self.assertAlmostEqual(T.effective_dp(10, 0.600)[0], 14.8, delta=0.05)

    def test_7600_table(self):
        """Page D-5: NPS 2, 5/8 in. shaft: A 0.057 / 0.200 / 0.400 by bearing, B 50, C 0.150 (60 deg),
        0.240 (90 deg), maximum allowable torque 943 lbf-in."""
        rows = T.lookup("7600", 2, "")
        self.assertEqual([r["A"] for r in rows], ["0.057", "0.2", "0.4"])
        self.assertEqual({(r["B"], r["C_60"], r["C_90"], r["max_torque_lbf_in"]) for r in rows},
                         {("50.0", "0.15", "0.24", "943.0")})
        self.assertEqual(len(T.torque_characteristics()), 81)

    def test_shaft_limit(self):
        row = T.lookup("7600", 2, "graphite")[0]
        r = T.valve_torque(a=float(row["A"]), b=float(row["B"]), c=float(row["C_90"]), dp_shutoff=150, p1_psig=150,
                           dp_eff_factor=T.DP_EFF_7600[("liquid", 90)], max_allowable_lbf_in=float(row["max_torque_lbf_in"]),
                           relative_strength_pct=53)
        self.assertAlmostEqual(r.max_allowable_lbf_in, 943 * 0.53)
        self.assertTrue(r.within_shaft_limit)


if __name__ == "__main__":
    unittest.main()
