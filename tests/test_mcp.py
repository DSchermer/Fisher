"""The MCP server speaks JSON-RPC over stdio and exposes every CLI command as a tool."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class MCPServer(unittest.TestCase):
    def exchange(self, messages):
        proc = subprocess.run([sys.executable, "-m", "fisher.mcp_server"], cwd=ROOT, check=True, text=True,
                              input="\n".join(json.dumps(m) for m in messages) + "\n", capture_output=True,
                              timeout=120)
        return [json.loads(x) for x in proc.stdout.splitlines() if x.strip()]

    def test_session(self):
        replies = self.exchange([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "sql", "arguments": {"query": "SELECT value FROM dataset_info WHERE key = 'version'"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "stem_load", "arguments": {"stem": 0.75, "temp_f": 400}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "show", "arguments": {"config_id": "nope"}}},
            {"jsonrpc": "2.0", "id": 6, "method": "nonsense"},
        ])
        self.assertEqual([r["id"] for r in replies], [1, 2, 3, 4, 5, 6])  # no reply to the notification
        self.assertEqual(replies[0]["result"]["protocolVersion"], "2025-06-18")
        names = {t["name"] for t in replies[1]["result"]["tools"]}
        self.assertTrue({"sql", "liquid", "gas", "valve_torque", "rotary_actuator", "stem_load"} <= names)
        gas = next(t for t in replies[1]["result"]["tools"] if t["name"] == "gas")
        self.assertEqual(gas["inputSchema"]["properties"]["units"]["enum"], ["us", "kpa", "bar"])
        self.assertIn("p1", gas["inputSchema"]["required"])
        self.assertFalse(replies[2]["result"]["isError"])
        self.assertRegex(json.loads(replies[2]["result"]["content"][0]["text"])[0]["value"], r"^\d{4}\.")
        self.assertEqual(json.loads(replies[3]["result"]["content"][0]["text"])["max_stem_load_lb"], 7980)
        self.assertTrue(replies[4]["result"]["isError"])
        self.assertEqual(replies[5]["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
