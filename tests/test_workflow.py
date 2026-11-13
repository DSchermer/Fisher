"""End-to-end sizing: service conditions -> Catalog 12 valves -> Catalog 14 actuators."""
import unittest

from fisher.workflow import size_application


class Workflow(unittest.TestCase):
    def test_liquid_reproduces_catalog_example(self):
        # README / Catalog 12: ES NPS 4 equal percentage between 8 in reducers: Cv 121.5 needed, 74% open (ES-5)
        r = size_application(fluid="liquid", q=800, p1=314.7, p2=289.7, gf=0.5, pipe_in=8, family="ES")
        hit = next(c for c in r["candidates"] if c["config_id"] == "152-1-10")
        self.assertAlmostEqual(hit["required_cv"], 121.5, delta=0.2)
        self.assertAlmostEqual(hit["opening"], 74, delta=0.5)
        self.assertEqual(r["dp_shutoff_psi"], 300)  # assumed P1 gauge
        self.assertTrue(any("shutoff" in a for a in r["assumptions"]))
        self.assertTrue(hit["actuators"]["options"])  # 585C rated on page A-3
        self.assertTrue(all("Catalog 14" in o["source"] for o in hit["actuators"]["options"]))
        self.assertTrue(all(20 <= c["opening"] <= 80 for c in r["candidates"]))

    def test_choked_liquid_checks(self):
        r = size_application(fluid="liquid", q=2200, p1=389.7, p2=114.7, gf=0.93, pv=41.9, pipe_in=6, motion="rotary")
        self.assertTrue(r["candidates"])
        self.assertEqual(r["skipped"], 0)
        self.assertTrue(any("FF = 0.96" in a for a in r["assumptions"]))
        c = r["candidates"][0]
        self.assertTrue(c["checks"]["choked"])
        self.assertGreater(c["checks"]["noise_dba"], 85)
        self.assertTrue(any("choked" in w for w in c["warnings"]))

    def test_gas_and_torque_fallback(self):
        r = size_application(fluid="gas", q=6e6, gg=0.6, t1=520, p1=214.7, p2=64.7, k=1.31, motion="rotary",
                             candidates=6)
        fams = {c["family"]: c for c in r["candidates"]}
        self.assertIn("9500", fams)
        cryo = fams.get("A31A-Cryogenic")
        self.assertIsNotNone(cryo)
        self.assertTrue(cryo["actuators"]["method"].startswith("torque"))  # no section C table: section D
        self.assertIn("page D-", cryo["actuators"]["note"])

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            size_application(fluid="liquid", p1=100, p2=50)


if __name__ == "__main__":
    unittest.main()
