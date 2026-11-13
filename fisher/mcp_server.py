"""MCP server (Model Context Protocol, stdio) exposing every fisher command as a tool, so an AI assistant
can look up the dataset and run the sizing tools deterministically.

    python3 -m fisher.mcp_server                       # speaks JSON-RPC 2.0 on stdin/stdout
    claude mcp add fisher -- python3 -m fisher.mcp_server   # register with Claude Code (run in this folder)

Standard library only. Tool names and input schemas are generated from the command-line parser
(fisher/__main__.py), so the CLI, the web UI and this server always run the same code. Every result is
JSON and carries the catalog page it came from where the command reports one.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sqlite3
import sys

from .__main__ import parser, run

SERVER = {"name": "fisher", "version": "1.0"}
DEFAULT_PROTOCOL = "2025-06-18"
INSTRUCTIONS = ("Fisher Catalog 12 (valve sizing) and Catalog 14 (actuator sizing) as deterministic tools. "
                "Values come from the catalogs as printed; results name their catalog page. Use 'sql' for the "
                "unified dataset (tables are described by docs/DATA_MODEL.md; e.g. SELECT name FROM sqlite_master).")


TOOL_HELP = {
    "families": "Catalog 12 valve families and how many configurations each has",
    "find": "Catalog 12 valve configurations matching family, size, characteristic, flow direction or text",
    "select": "Catalog 12 configurations that pass a required Cv within an opening range",
    "show": "One Catalog 12 configuration: every printed coefficient, attributes, flags and source page",
    "liquid": "Catalog 12 liquid sizing: required Cv, choked-flow check (US units)",
    "gas": "Catalog 12 compressible-fluid sizing: required Cv (units us, kpa or bar)",
    "liquid_flow": "Catalog 12 flow prediction: liquid flow through a given Cv",
    "steam": "Saturated steam properties from the Catalog 12 table, by pressure or temperature",
}
PARAM_HELP = {  # US units, as the catalog's equations use them
    "q": "flow: gpm (liquid) or scfh (gas)", "w": "mass flow, lb/h", "p1": "inlet pressure, psia (gas with units kpa/bar: kPa or bar abs)",
    "p2": "outlet pressure, psia (gas with units kpa/bar: kPa or bar abs)", "gf": "liquid specific gravity", "gg": "gas specific gravity",
    "m": "molecular weight", "k": "ratio of specific heats", "xt": "pressure drop ratio factor xT",
    "t1": "inlet temperature, deg R", "z": "compressibility factor", "fp": "piping geometry factor Fp",
    "fr": "Reynolds number factor FR", "fl": "liquid pressure recovery factor FL", "pv": "vapor pressure, psia",
    "ff": "critical pressure ratio factor FF", "pc": "critical pressure, psia", "cv": "flow coefficient Cv",
    "gamma1": "inlet density, lb/ft3", "config_id": "Catalog 12 configuration id, e.g. 152-1-8 (from find)",
    "family": "valve family, e.g. ED, V150", "nps": "valve size, NPS", "dp": "pressure drop, psi",
    "psia": "pressure, psia", "temp_f": "temperature, F", "valve": "valve, e.g. 8532 or V150/V200/V300",
    "dp_shutoff": "shutoff pressure drop, psi", "table_id": "Catalog 14 table id (from c14_tables)",
    "characteristic": "e.g. linear, equal percentage", "flow_direction": "e.g. flow up, flow down",
    "text": "text to search for", "no_restricted": "exclude restricted trim", "no_aliases": "do not expand aliases",
    "min_open": "smallest acceptable opening, % or degrees", "max_open": "largest acceptable opening",
    "n1": "N1 constant (default 1.00 for gpm, psia)", "nu": "kinematic viscosity, centistokes",
    "d": "valve inlet diameter, inches", "port": "port diameter, inches", "travel": "valve travel, inches",
    "actuator": "actuator type, e.g. 585C, 657, 1052", "yoke_boss": "yoke boss diameter as printed, e.g. 2-13/16",
    "balance": "balanced or unbalanced", "leakage": "leakage class, e.g. IV, V",
    "angle": "angle of opening, degrees (0 = closed)", "flow": "flow direction: forward, reverse",
    "shaft": "shaft diameter", "section": "Catalog 14 section: A, B, C or D",
    "query": "read-only SQL, e.g. SELECT * FROM torque_factor WHERE valve = '8532' LIMIT 5",
    "valve_code": "Catalog 14 valve code, e.g. ED", "limit": "maximum results",
    "km": "valve recovery coefficient Km", "schedule": "pipe schedule, e.g. 40", "g": "liquid specific gravity",
    "style": "valve style / trim for the noise equation", "fluid": "liquid or gas",
    "strength": "shaft relative strength at temperature, percent of MAST",
    "pressure_class": "pressure class filter, e.g. CL150", "construction": "seal / bearing filter, e.g. Phoenix",
    "variant": "valve variant, e.g. 'with Attenuator'", "b_key": "which printed B to use, e.g. PTFE",
    "mast_key": "which shaft material's MAST to use", "supply_psig": "air supply or cylinder pressure, psig",
    "action": "PDTC, PDTO, 'spring to close', 'air to close'", "diaphragm": "air-to-diaphragm range, e.g. 0-33",
}


def _subparsers() -> dict[str, argparse.ArgumentParser]:
    for a in parser()._actions:
        if isinstance(a, argparse._SubParsersAction):
            return dict(a.choices)
    return {}


def _help(p: argparse.ArgumentParser, name: str) -> str:
    for a in parser()._actions:
        if isinstance(a, argparse._SubParsersAction):
            for ch in a._choices_actions:
                if ch.dest == name and ch.help:
                    return ch.help
    return p.description or name


def tools() -> list[dict]:
    out = []
    for name, p in _subparsers().items():
        props, required = {}, []
        for a in p._actions:
            if isinstance(a, argparse._HelpAction):
                continue
            key = a.dest
            if isinstance(a, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
                schema = {"type": "boolean"}
            elif a.type in (float, int):
                schema = {"type": "number" if a.type is float else "integer"}
            else:
                schema = {"type": "string"}
            if a.choices:
                schema["enum"] = list(a.choices)
            if a.help or key in PARAM_HELP:
                schema["description"] = a.help or PARAM_HELP[key]
            if a.default not in (None, argparse.SUPPRESS) and not isinstance(a, argparse._StoreTrueAction):
                schema["default"] = a.default
            props[key] = schema
            if a.required or not a.option_strings:
                required.append(key)
        tool = name.replace("-", "_")
        out.append({"name": tool, "description": TOOL_HELP.get(tool) or _help(p, name),
                    "inputSchema": {"type": "object", "properties": props, "required": required,
                                    "additionalProperties": False}})
    return out


def to_argv(tool: str, args: dict) -> list[str]:
    name = tool.replace("_", "-")
    p = _subparsers()[name]
    argv, positional = [name], []
    for a in p._actions:
        if isinstance(a, argparse._HelpAction) or a.dest not in args or args[a.dest] is None:
            continue
        v = args[a.dest]
        if not a.option_strings:
            positional.append(str(v))
        elif isinstance(a, argparse._StoreTrueAction):
            if v:
                argv.append(a.option_strings[-1])
        else:
            argv += [a.option_strings[-1], str(v)]
    unknown = set(args) - {a.dest for a in p._actions}
    if unknown:
        raise ValueError(f"unknown arguments: {sorted(unknown)}")
    return argv + (["--", *positional] if positional else [])


def call_tool(tool: str, args: dict) -> tuple[bool, str]:
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            result = run(to_argv(tool, args or {}))
        return True, json.dumps(result, default=str)
    except SystemExit:
        msg = err.getvalue().strip().splitlines()
        return False, msg[-1] if msg else "invalid input"
    except KeyError as e:
        return False, f"not found: {e.args[0] if e.args else tool}"
    except (ValueError, IndexError, TypeError, sqlite3.Error) as e:
        return False, str(e)


def handle(msg: dict) -> dict | None:
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:  # a notification (e.g. notifications/initialized): no reply
        return None
    if method == "initialize":
        version = (msg.get("params") or {}).get("protocolVersion") or DEFAULT_PROTOCOL
        result = {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": SERVER, "instructions": INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tools()}
    elif method == "tools/call":
        params = msg.get("params") or {}
        ok, text = call_tool(params.get("name", ""), params.get("arguments") or {})
        result = {"content": [{"type": "text", "text": text}], "isError": not ok}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            try:
                reply = handle(msg)
            except Exception as e:  # never let one request kill the server
                reply = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32603, "message": str(e)}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
