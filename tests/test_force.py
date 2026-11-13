"""Catalog 14 force method (section B), checked against its sample calculations (pages B-77 to B-80.4)."""
import unittest

from fisher import force as F


class SampleCalculations(unittest.TestCase):
    def test_585c_b77(self):
        """NPS 4 ES, PDTC, flow up, metal seat, PTFE packing, 1/2 in. stem, dP shutoff 100 psi,
        customer seat load 50 lb/in: 1503 + 687 + 50 = 2240 lb."""
        g = F.port_geometry(4.375)
        self.assertEqual((g["area_in2"], g["circumference_in"]), (15.03, 13.74))
        v = F.valve_forces(p1=100, balanced=False, flow="up", action="PDTC", area_in2=g["area_in2"],
                           stem_area_in2=F.stem_area(0.5), seat=F.seat_load("ES", 4.375, "IV", 100, lb_per_inch=50),
                           packing_lb=F.packing_friction(0.5, "PTFE")["pounds"])
        self.assertEqual(v.pressure_tends_to, "open")
        self.assertEqual((v.A, v.B, v.C, v.closing_force), (1503, 687, 50, 2240))

    def test_685se_b80_1(self):
        """NPS 6 HPT, PDTC, flow down, metal seat, class V, dP 750 psi, unbalance area 0.206 (table 2C),
        circumference 16.89, 1 in. stem PTFE: A = 155, seat 192 lb/in -> 3243, C = 100.
        The catalog rounds 191.5 lb/in up to 192 before multiplying; the code keeps 191.5."""
        self.assertEqual(F.unbalance_areas(5.375, "HPT")[0]["unbalance_area_in2"], 0.206)
        seat = F.seat_load("HPT", 5.375, "V", 750)
        self.assertAlmostEqual(seat.per_inch, 191.5)
        self.assertAlmostEqual(seat.pounds, 3243, delta=3243 * 0.005)
        v = F.valve_forces(p1=750, balanced=True, flow="down", action="PDTC", area_in2=0.206,
                           stem_area_in2=F.stem_area(1), seat=seat, packing_lb=F.packing_friction(1, "PTFE")["pounds"])
        self.assertAlmostEqual(v.A, 155, delta=0.6)
        self.assertEqual(v.C, 100)

    def test_685sr_b80_3(self):
        """NPS 16 Large ET, PDTC, flow up (pressure tends to close), class V, dP 200, unbalance 0.49,
        stem area 1.23, circumference 34.56, 1.25 in. stem: A = 148, seat 124 lb/in -> 4299, C = 120."""
        seat = F.seat_load("ET", 11, "V", 200, circumference_in=34.56)
        self.assertAlmostEqual(seat.pounds, 4299, delta=1)
        v = F.valve_forces(p1=200, balanced=True, flow="up", action="PDTC", area_in2=0.49, stem_area_in2=1.23,
                           seat=seat, packing_lb=F.packing_friction(1.25, "PTFE")["pounds"])
        self.assertEqual(v.pressure_tends_to, "close")
        self.assertAlmostEqual(v.A, 148)
        self.assertEqual(v.C, 120)


class Tables(unittest.TestCase):
    def test_unbalance_areas_per_construction(self):  # page B-5, 4.375 in. port
        areas = {round(a["unbalance_area_in2"], 3) for a in F.unbalance_areas(4.375)}
        self.assertEqual(areas, {0.154, 0.25, 0.51})
        self.assertEqual([a["unbalance_area_in2"] for a in F.unbalance_areas(4.375, "CAV4")], [0.51])

    def test_pressure_tends_to(self):  # figures 1 and 2, page B-2
        self.assertEqual(F.pressure_tends_to(False, "up", "PDTC"), "open")
        self.assertEqual(F.pressure_tends_to(False, "down", "PDTC"), "close")
        self.assertEqual(F.pressure_tends_to(True, "down", "PDTC"), "open")
        self.assertEqual(F.pressure_tends_to(True, "up", "PDTC"), "close")

    def test_seat_rules(self):
        self.assertEqual(F.seat_load("ED", 3.4375, "IV", 0, circumference_in=10.8).per_inch, 40)
        self.assertEqual(F.seat_load("ED", 5.375, "IV", 0).per_inch, 80)
        with self.assertRaises(KeyError):
            F.seat_load("ED", 3.4375, "VI", 100)

    def test_packing(self):
        self.assertEqual(F.packing_friction(0.75, "graphite", 600)["pounds"], 660)  # table 6
        self.assertEqual(F.packing_friction(1, "ISO-Seal PTFE", 1500)["pounds"], 560)  # table 6D
        with self.assertRaises(ValueError):
            F.packing_friction(0.75, "graphite")  # depends on pressure class


if __name__ == "__main__":
    unittest.main()


class ActuatorSelection(unittest.TestCase):
    def test_585c_b77(self):
        """2240 lb required at 80 psig supply, 2-13/16 in. yoke boss, 1/2 in. stem: size 25 falls short
        (2600 x 0.8 = 2080 lb), size 50 passes. The sample used older Table 8 values (4710 lb); the
        current table lists 4600 lb, giving 3680 lb, still enough."""
        from fisher.actuator_force import select_585c
        opts = select_585c(2240, 80, yoke_boss="2-13/16", stem_in=0.5)
        self.assertEqual([(o.size, o.force_available_lb, o.passes) for o in opts],
                         [("25", 2080, False), ("50", 3680, True)])

    def test_657_b81_calculated(self):
        """NPS 2 ES on a 657 size 40: 15 psig x 69 = 1035, minus 3 psig initial (207) = 828; required
        63 + 363 + 50 = 476; net 352 lb; ideal rate 352 / 1.125 = 313 lb/in -> spring 1F177027092 (275 lb/in)."""
        from fisher.actuator_force import DIAPHRAGM_AREA, spring_rate_calc, springs_for_rate
        req = F.valve_forces(p1=15, balanced=False, flow="up", action="PDTC", area_in2=4.2,
                             stem_area_in2=F.stem_area(0.5), seat=F.seat_load("ES", 2.3125, "IV", 15, lb_per_inch=50),
                             packing_lb=50).closing_force
        self.assertAlmostEqual(req, 476, delta=0.5)
        calc = spring_rate_calc(req, 1.125, DIAPHRAGM_AREA["40"])
        self.assertAlmostEqual(calc["net_force_lb"], 352, delta=0.5)
        self.assertAlmostEqual(calc["ideal_spring_rate_lb_in"], 313, delta=0.5)
        self.assertEqual(springs_for_rate("657", "40", calc["ideal_spring_rate_lb_in"])[0]["spring"], "1F177027092")

    def test_657_table_method(self):
        """The same spring at 1-1/8 in. travel on page B-33: 759 lb, bench set 3-7 psig."""
        from fisher.actuator_force import select_diaphragm
        hits = select_diaphragm(476, 1.125, actuator="657", supply="0-18", yoke_boss="2-13/16")
        s = [h for h in hits if h["spring"] == "1F177027092" and h["size"].startswith("40")][0]
        self.assertEqual((s["force_lb"], s["bench_set"], s["spring_rate_lb_in"], s["printed_label"]),
                         (759, "3-7", "275", "B-33"))
        self.assertTrue(all(h["force_lb"] >= 476 for h in hits))


class AdditionalForces(unittest.TestCase):  # page B-18, figures 4 and 4A
    def test_figure_4_vector(self):
        from fisher import force
        r = force.piston_ring_friction(10, 4736, valve="EHD")  # 10-in line ends at the chart top: 1600 lb
        self.assertAlmostEqual(r["force_lb"], 1610, delta=15)
        self.assertFalse(r["approximate"])
        # one printed line carries two ports: 2.875 in (EHD) and 3.625 in (HPD)
        self.assertEqual(force.piston_ring_friction(2.875, 1000, valve="EHD")["slope_lb_per_psi"],
                         force.piston_ring_friction(3.625, 1000, valve="HPD")["slope_lb_per_psi"])

    def test_figure_4a_raster(self):
        from fisher import force
        r = force.piston_ring_friction(3.44, 4000, valve="TBX")  # chart: about 1100 lb at 4000 psi
        self.assertAlmostEqual(r["force_lb"], 1100, delta=60)
        self.assertTrue(r["approximate"])
        steep = force.piston_ring_friction(19.94, 1000, valve="CVX")["slope_lb_per_psi"]
        self.assertGreater(steep, force.piston_ring_friction(13.75, 1000, valve="CVX")["slope_lb_per_psi"])

    def test_cryogenic_seal_ring(self):
        from fisher import force
        self.assertAlmostEqual(force.cryogenic_seal_ring_friction(4)["force_lb"], 28 * 3.141592653589793 * 4)
        self.assertEqual(force.cryogenic_seal_ring_friction(8)["lb_per_inch"], 34)
