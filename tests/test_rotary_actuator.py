"""Rotary actuator torque output (Catalog 14 section D) and selection against valve torque."""
import unittest

from fisher import rotary_actuator as ra
from fisher import torque


def rows(**match):
    return [r for r in ra.actuator_torque() if all(r[k] == v for k, v in match.items())]


class ActuatorTorque(unittest.TestCase):
    def test_actuators(self):
        self.assertEqual({r["actuator"] for r in ra.actuator_torque()}, {"1051", "1052", "1061", "1068", "2052"})

    def test_1051_values(self):  # page D-123: 0-18 psig, spring 10B1523X012, size 33
        r = rows(printed_label="D-123", spring="10B1523X012", action="PDTC", quantity="TB")
        self.assertEqual((r[0]["size"], r[0]["diaphragm_psig"], float(r[0]["value"])), ("33", "0-18", 203))
        td = rows(printed_label="D-123", spring="10B1523X012", action="PDTO", quantity="TD_MAX_ROTATION")
        self.assertEqual({(float(x["max_rotation_deg"]), float(x["value"])) for x in td}, {(60, 435), (90, 203)})

    def test_1052_spring_output(self):  # page D-111, Table 5: size 70, 0-55 psi, 10.1 psig initial compression
        r = rows(printed_label="D-111", table_no="2", size="70", diaphragm_psig="0-55", initial_compression_psig="10.1")
        got = {float(x["angle_deg"]): float(x["value"]) for x in r}
        self.assertEqual(got[0], 12105)
        self.assertEqual(got[90], 4819)
        self.assertTrue(all(x["action"] == "PDTC" for x in r))

    def test_1068_spring_return(self):  # page D-148, Table 1: CV500 spring to close, size 5i at 80 psi
        r = rows(printed_label="D-148", table_no="1", size="5i", supply="80 psig")
        q = {x["quantity"]: float(x["value"]) for x in r if x["quantity"] in ("SEATING", "UNSEATING")}
        self.assertEqual(q, {"SEATING": 155, "UNSEATING": 185})
        self.assertEqual(r[0]["action"], "spring to close")
        self.assertEqual(r[0]["used_with"], "CV500")

    def test_v300_sample_selection(self):  # pages D-113/D-114: the 1052 size 70 cannot cover the valve
        km = dict(zip(range(10, 100, 10), [0.76, 0.64, 0.69, 0.61, 0.62, 0.51, 0.53, 0.47, 0.40]))
        actual = {10: 400, 20: 350, 30: 250, 40: 150, 50: 100, 60: 70, 70: 50, 80: 40, 90: 30}
        (v,) = torque.valve_torque_catalog("V150/V200/V300", 12, variant="with Attenuator", dp_shutoff=440,
                                           p1_psig=440, fluid="gas", k=km, actual_dp=actual)
        res = ra.select(v.breakout_lbf_in, v.dynamic_lbf_in, valve="V300", actuator="1052", action="PDTC",
                        attenuator=True, diaphragm_psig="0-55")
        c70 = next(c for c in res if c.size == "70" and c.initial_compression_psig == "10.1")
        self.assertTrue(c70.checks["breakout"])  # 12,105 at 0 deg vs 4,760
        self.assertTrue(c70.checks["dynamic_20"])
        self.assertFalse(c70.checks["dynamic_40"])  # 12,448 < 16,950
        self.assertFalse(c70.passes)

    def test_1061_per_psig(self):  # page D-142: size 30, 25 lbf-in/psig at 0 or 90 deg
        (c,) = [c for c in ra.select(1000, {90: 1000}, actuator="1061", supply_psig=60) if c.size == "30"]
        self.assertEqual(c.dynamic_available[90], 25 * 60)
        self.assertTrue(c.passes)

    def test_valve_filter(self):
        res = ra.select(1000, {60: 500}, valve="CV500", flow="forward")
        self.assertTrue(res)
        self.assertTrue(all("cv500" in c.used_with.lower() or c.used_with == "All Valves" for c in res))
        self.assertTrue(res[0].passes)


if __name__ == "__main__":
    unittest.main()
