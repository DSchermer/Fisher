"""Data-quality fixes: motion by valve type, pressure class, size fallbacks, Catalog 14 valve families,
footnote text, and the pressure-drop-method rules on pages C-4 to C-7."""
import unittest

from fisher import Catalog, actuators, db, integrate
from fisher.catalog import parse_nps


class Motion(unittest.TestCase):
    def test_ball_valves_are_rotary(self):
        cat = Catalog.load()
        for fam in ("SIS", "Z500"):
            self.assertTrue(all(c.motion == "rotary" for c in cat.configs.values() if c.family == fam), fam)
        self.assertTrue(all(c.motion == "reference" for c in cat.configs.values() if c.family == "Fd Style Modifiers"))
        self.assertEqual(db.query("SELECT motion FROM valve_family WHERE family = 'SIS'")[0]["motion"], "rotary")

    def test_rotary_without_section_c_points_to_torque_method(self):
        c = next(c for c in Catalog.load().configs.values() if c.family == "Z500")
        self.assertIn("valve_torque_catalog('Z500'", integrate.actuators_for_config(c).note)

    def test_gx_preselected(self):
        c = next(c for c in Catalog.load().configs.values() if c.family == "GX")
        self.assertIn("preselected actuator", integrate.actuators_for_config(c, 100).note)


class PressureClass(unittest.TestCase):
    def test_parsed_from_title(self):
        n = db.query("SELECT COUNT(*) n FROM valve_config WHERE pressure_class != ''")[0]["n"]
        self.assertGreater(n, 2200)
        r = db.query("SELECT pressure_class, class_min, class_max FROM valve_config "
                     "WHERE pressure_class = 'CL125 - CL600' LIMIT 1")[0]
        self.assertEqual((r["class_min"], r["class_max"]), (125, 600))


class Sizes(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_nps("All Sizes 1 and 2"), [1.0, 2.0])
        self.assertEqual(parse_nps("All Sizes 1/2 - 2"), [0.5, 0.75, 1.0, 1.5, 2.0])

    def test_fallbacks(self):
        cat = Catalog.load()
        self.assertEqual(cat.get("139-1-1").sizes, [8.0, 10.0])  # EH cage code A1, body size 8 & 10
        self.assertEqual(cat.get("301-1-1").sizes, [1.0])  # V150 'NPS 1 Micro-Notch Ball' in the title
        missing = {c.family for c in cat.configs.values() if not c.sizes}
        self.assertEqual(missing, {"81000", "83000", "87000", "89000", "Fd Style Modifiers"})  # sized by orifice


class Catalog14(unittest.TestCase):
    def test_valve_family(self):
        fams = {r["valve_family"] for r in db.query("SELECT DISTINCT valve_family FROM actuator_rating WHERE section='C'")}
        self.assertIn("A11", fams)
        self.assertIn("V150/V200/V300", fams)
        self.assertFalse(any("CL" in f or "S17400" in f for f in fams))

    def test_footnotes(self):
        notes = db.query("SELECT text FROM c14_page_note WHERE printed_label = 'D-26.6' AND number = 1")
        self.assertTrue(notes[0]["text"].startswith("Nominal diameter of spline shaft"))

    def test_c5_rules(self):  # page C-5 tables 2 and 3; C-6 table 4; C-7 table 5
        self.assertEqual(actuators.required_angles("V200", 90), [70])
        self.assertEqual(actuators.required_angles("V500", 90), [60, 90])
        dp, _ = actuators.effective_dp_c14("9500", 90, "gas", 100, disk="conventional")
        self.assertAlmostEqual(dp, 0.14 * 114.7)
        self.assertEqual(actuators.k_values_c14("V150", 4), {"table 4": {60: 0.233, 70: 0.194}})
        self.assertEqual(actuators.k_values_c14("8532", 20)["table 4"][80], 0.117)
        self.assertEqual(actuators.k_values_c14("V500", 3)["full port"][90], 0.161)


if __name__ == "__main__":
    unittest.main()
