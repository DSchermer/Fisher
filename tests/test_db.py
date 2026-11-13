"""The unified dataset (data/fisher.db): complete, documented, provenance on every row, and it
reproduces values printed in both catalogs."""
import csv
import re
import sqlite3
import unittest
from pathlib import Path

from fisher import Catalog, actuators, db, integrate

ROOT = Path(__file__).resolve().parent.parent


class Dataset(unittest.TestCase):
    def q(self, sql, params=()):
        return db.query(sql, params)

    def one(self, sql, params=()):
        return list(self.q(sql, params)[0].values())[0]

    def test_read_only(self):
        con = db.connect()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("DELETE FROM source")
        finally:
            con.close()

    def test_matches_the_tools(self):
        self.assertEqual(self.one("SELECT COUNT(*) FROM valve_config"), len(Catalog.load().configs))
        self.assertEqual(self.one("SELECT COUNT(*) FROM actuator_rating"), len(actuators.ratings()))
        with open(ROOT / "data" / "coefficients.csv", encoding="utf-8") as fh:
            self.assertEqual(self.one("SELECT COUNT(*) FROM flow_coefficient"), sum(1 for _ in csv.DictReader(fh)))
        cfg = Catalog.load().get("152-1-8")
        self.assertEqual(self.one("SELECT COUNT(*) FROM valve_actuator_link WHERE config_id='152-1-8'"),
                         len(integrate.actuators_for_config(cfg).ratings))

    def test_provenance(self):
        for table in ("valve_config", "actuator_rating", "page_note", "reference_table"):
            self.assertEqual(self.one(f"SELECT COUNT(*) FROM {table} WHERE pdf_page IS NULL OR printed_label = ''"), 0, table)
        self.assertEqual(self.one("SELECT COUNT(*) FROM actuator_rating WHERE confirmed = 0"), 0)

    def test_catalog12_values(self):
        # ED NPS 4 linear cage (ED-3): Cv 236 and XT 0.688 at 100 % travel (quoted on page 2-15)
        r = self.q("SELECT rated_cv, rated_xt, port_in, travel_in FROM valve_config WHERE config_id='122-1-10'")[0]
        self.assertEqual((r["rated_cv"], r["rated_xt"]), (236, 0.688))
        self.assertEqual(self.one("SELECT value FROM flow_coefficient WHERE config_id='122-1-8' AND coefficient='Cv' AND position=80"), 133)
        self.assertEqual(self.one("SELECT temp_f FROM steam_saturated WHERE psia=40"), 267.25)
        self.assertEqual(self.one("SELECT value FROM equation_constant WHERE name='N7' AND units LIKE 'scfh%'"), 1360)

    def test_catalog14_values_by_parsed_columns(self):
        # C-26: 8532 NPS 14, 1052 size 70, 33 psig supply, at 0 / 60 / 90 degrees: 201 / 10 / 1 psi
        rows = self.q("SELECT angle_deg, max_dp FROM actuator_rating WHERE printed_label='C-26' AND valve_nps=14 "
                      "AND actuator_size='70' AND supply='33' AND unit='psi' ORDER BY angle_deg")
        self.assertEqual([(r["angle_deg"], r["max_dp"]) for r in rows], [(0, 201), (60, 10), (90, 1)])
        # A-3: 585C size 60, 1 inch port, 1.125 travel, supply 50 / 60 / 80 / 100 psig
        rows = self.q("SELECT supply, max_dp FROM actuator_rating WHERE printed_label='A-3' AND port_in=1 "
                      "AND travel_in=1.125 AND actuator_size='60' ORDER BY max_dp")
        self.assertEqual([(r["supply"], r["max_dp"]) for r in rows], [("50", 2925), ("60", 3562), ("80", 4834), ("100", 6000)])
        self.assertEqual(self.one("SELECT COUNT(*) FROM actuator_rating WHERE supply='' OR actuator_size=''"), 0)

    def test_joined_view(self):
        rows = self.q("SELECT max_dp FROM v_valve_actuator WHERE config_id='152-1-8' AND unit='psi' AND max_dp>=300 ORDER BY max_dp")
        self.assertEqual([r["max_dp"] for r in rows], [374, 375, 460, 483])

    def test_data_dictionary_is_complete(self):
        doc = (ROOT / "docs" / "DATA_MODEL.md").read_text(encoding="utf-8")
        tables = [r["name"] for r in self.q("SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tables:
            self.assertIn(f"## `{t}`", doc, t)
            for col in self.q(f"PRAGMA table_info({t})"):
                self.assertRegex(doc, rf"\| `{re.escape(col['name'])}` \| \w+ \| .+ \|", f"{t}.{col['name']}")


if __name__ == "__main__":
    unittest.main()
