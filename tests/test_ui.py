"""The UI's API layer: form parameters -> the same commands as the CLI."""
import unittest

from fisher.ui import call, to_argv


class Api(unittest.TestCase):
    def test_argv(self):
        self.assertEqual(to_argv("show", {"config_id": "122-1-8"}), ["show", "122-1-8"])
        self.assertEqual(to_argv("find", {"family": "ED", "nps": "", "no_restricted": "on"}),
                         ["find", "--family", "ED", "--no-restricted"])

    def test_results_match_cli(self):
        status, out = call("liquid", {"q": "2200", "p1": "389.7", "p2": "114.7", "gf": "0.93",
                                      "fl": "0.84", "pv": "41.9", "ff": "0.90"})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(out["cv"], 134.6, places=1)
        status, out = call("size-valve", {"config_id": "309-1-3", "p1": "214.7", "p2": "64.7", "k": "1.31",
                                          "q": "6e6", "gg": "0.6", "t1": "520"})
        self.assertEqual((status, out["position_basis"]), (200, "deg_rotation"))

    def test_errors_are_messages(self):
        self.assertEqual(call("liquid", {"q": "abc", "p1": "1", "p2": "0", "gf": "1"})[0], 400)
        self.assertIn("outside", call("steam", {"psia": "99999"})[1]["error"])
        self.assertEqual(call("show", {"config_id": "nope"})[1]["error"], "not found: nope")


if __name__ == "__main__":
    unittest.main()
