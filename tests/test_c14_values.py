"""Catalog 14 sections B (force method) and D (torque method) as typed values (c14_table_value):
values printed in the catalog are found under the right keys and column, and the second reader
confirms nearly every row."""
import unittest

from fisher import db


def values(label, column_like, **keys):
    sql = "SELECT value, value_raw, confirmed FROM c14_table_value WHERE printed_label = ? AND column_path LIKE ?"
    params = [label, column_like]
    for k, v in keys.items():
        sql += " AND json_extract(keys, ?) = ?"
        params += [f'$."{k}"', v]
    return db.query(sql, tuple(params))


class C14Values(unittest.TestCase):
    def check(self, expected, label, column_like, **keys):
        rows = values(label, column_like, **keys)
        self.assertIn(expected, [r["value"] for r in rows], (label, column_like, keys, rows))
        self.assertTrue(all(r["confirmed"] for r in rows if r["value"] == expected))

    def test_585c_force_at_100_psig(self):  # page B-24, Table 8
        self.check(2600, "B-24", "%SUPPLY › lb", SIZE="25")

    def test_packing_friction(self):  # page B-16, Table 6: 5/16 inch stem, single PTFE
        self.check(20, "B-16", "%PTFE › Single", **{"STEM DIAMETER, INCH": "5/16"})

    def test_785c_spring(self):  # page B-27.10, Table 4, both halves of a side-by-side table
        self.check(1500, "B-27.10", "PRE- LOAD%", **{"SPRING NUMBER": "785C-100K-335-7K-115-OP-SR-F1"})
        self.check(741, "B-27.10", "SPRING RATE%", **{"SPRING NUMBER": "785C-100K-335-7K-115-OP-SR-F1"})
        self.check(496, "B-27.10", "SPRING RATE%", **{"SPRING NUMBER": "785C-100K-335-8K-216-OP-SR-F1"})

    def test_657c_force_with_bench_set(self):  # page B-46.1: "207 (3-15)"
        rows = values("B-46.1", "1.78 (45)")
        self.assertIn(("207 (3-15)", 207), [(r["value_raw"], r["value"]) for r in rows])

    def test_shaft_limits(self):  # page D-26.6: spline and square shafts are separate row groups
        self.check(1424, "D-26.6", "%S17400 H1025", NPS="3", **{"Shaft Diameter(1) (Inch)": "5/8"})
        self.check(939, "D-26.6", "%S17400 H1025", NPS="3", **{"Square Size (mm)": "11"})

    def test_a11_max_torque(self):  # page D-55
        self.check(463, "D-55", "CL600%PEEK Bearing", **{"VALVE SIZE, NPS": "3"})

    def test_z500_mast(self):  # page D-122.3: large values not written in exponent form
        rows = values("D-122.3", "%Precipitation Hardened%", BORE="12", CLASS="150-600")
        self.assertEqual(rows[0]["value"], 1553000)
        self.assertEqual(rows[0]["value_raw"], "1553000")

    def test_2052_torque(self):  # page D-112
        self.check(226, "D-112", "%PDTO) › Tb", **{"ACTUATOR SIZE": "1", "AIR TO DIAPHRAGM": "2 barg (29 psig)"})

    def test_confirmation_rate(self):
        for section in "BD":
            r = db.query("SELECT COUNT(*) n, SUM(confirmed != '') ok FROM c14_table_value "
                         "WHERE section = ? AND value IS NOT NULL", (section,))[0]
            self.assertGreater(r["n"], 7000)
            self.assertGreater(r["ok"] / r["n"], 0.999, section)

    def test_linked_to_printed_tables(self):
        r = db.query("SELECT COUNT(*) n, SUM(table_id != '') linked FROM c14_table_value")[0]
        self.assertGreater(r["linked"] / r["n"], 0.99)
        self.assertEqual(db.query("SELECT COUNT(*) n FROM c14_table_value v WHERE table_id != '' AND NOT EXISTS "
                                  "(SELECT 1 FROM reference_table t WHERE t.table_id = v.table_id)")[0]["n"], 0)


if __name__ == "__main__":
    unittest.main()
