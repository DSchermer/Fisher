"""Build the unified dataset: data/fisher.db (SQLite) and its data dictionary docs/DATA_MODEL.md.

One schema across Fisher Catalog 12 (valve sizing) and Catalog 14 (actuator sizing), built from the
extracted, checked files in data/. Every row keeps where it came from (catalog, PDF page, printed page
label) and every quantity has a fixed unit stated in the column name or its description.

The schema below is the single definition of the dataset: the database and the data dictionary are
both generated from it.

Usage:
    python extract/build_db.py data/fisher.db docs/DATA_MODEL.md
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fisher import Catalog, actuators, integrate, reference, sizing  # noqa: E402

DATA = ROOT / "data"

# table -> (description, [(column, sqlite type, description)])
SCHEMA: dict[str, tuple[str, list[tuple[str, str, str]]]] = {
    "source": ("The documents the data comes from.", [
        ("catalog", "TEXT PRIMARY KEY", "Short id used in every other table: 'C12' or 'C14'"),
        ("title", "TEXT", "Document title"),
        ("document_number", "TEXT", "Emerson document number"),
        ("edition", "TEXT", "Edition as printed on the index page"),
        ("sha256", "TEXT", "SHA-256 of the PDF the data was extracted from"),
        ("url", "TEXT", "Where the PDF was downloaded"),
    ]),
    "page": ("Every catalog page that contributes data, with its printed label and heading.", [
        ("catalog", "TEXT", "'C12' or 'C14'"),
        ("pdf_page", "INTEGER", "1-based page number in the PDF"),
        ("printed_label", "TEXT", "Page number as printed, e.g. 'ED-1', '2-33', 'A-3'"),
        ("section", "TEXT", "Catalog section: C12 '1', '2', '3'; C14 'A', 'B', 'C', 'D'"),
        ("valve_family", "TEXT", "C12 section 1 pages: the valve family the page belongs to"),
        ("page_kind", "TEXT", "C12: coefficient_table, text, figure, redirect, blank"),
        ("heading", "TEXT", "C14: the page heading (actuator, valve, construction, leakage class)"),
    ]),
    "valve_family": ("Valve families in Catalog 12, with how Catalog 14 covers them.", [
        ("family", "TEXT PRIMARY KEY", "Family as used in Catalog 12 page labels, e.g. 'ED', 'V150', '8580'"),
        ("motion", "TEXT", "'sliding-stem' or 'rotary' (from the coefficient tables: % travel or degrees)"),
        ("configurations", "INTEGER", "Number of configurations in valve_config"),
        ("c12_pages", "TEXT", "Printed labels of the family's coefficient pages"),
        ("c14_sliding_codes", "TEXT", "C14 section A valve codes this family maps to (ED, ET, ES, EZ, D, EWD, EWS, EWT)"),
        ("c14_balance", "TEXT", "Balanced or Unbalanced per C14 page A-2 (sliding-stem families covered by section A)"),
        ("c14_linked_configs", "INTEGER", "Configurations with at least one C14 actuator rating"),
    ]),
    "valve_config": ("One valve configuration: one block of a Catalog 12 coefficient table.", [
        ("config_id", "TEXT PRIMARY KEY", "Stable id '<pdf page>-<table>-<block>', e.g. '152-1-8'"),
        ("family", "TEXT", "Valve family (valve_family.family)"),
        ("motion", "TEXT", "'sliding-stem' or 'rotary'"),
        ("catalog", "TEXT", "'C12'"),
        ("pdf_page", "INTEGER", "PDF page"),
        ("printed_label", "TEXT", "Printed page label"),
        ("title", "TEXT", "Page title, table title and section, joined with ' | '"),
        ("characteristic", "TEXT", "Inherent characteristic as printed (Linear, Equal Percentage, ...); empty if not stated"),
        ("flow_direction", "TEXT", "Flow direction as printed (Flow Up, Flow Down, Forward Flow, ...); empty if not stated"),
        ("nps_text", "TEXT", "Size cell as printed, e.g. '1-1/2', '2 & 3 x 2', '80' (DN)"),
        ("port_in", "REAL", "Port diameter, inches (sliding-stem; from the table's inch column)"),
        ("travel_in", "REAL", "Maximum or total travel, inches (sliding-stem)"),
        ("position_basis", "TEXT", "How openings are given: 'pct_travel', 'deg_rotation', 'relative_flow_coefficient'"),
        ("rated_cv", "REAL", "Cv at the largest listed opening"),
        ("rated_xt", "REAL", "XT at the largest listed opening, if listed"),
        ("fl_single", "REAL", "FL printed as a single value for the configuration, if any"),
        ("restricted_trim", "INTEGER", "1 if the catalog marks the configuration as restricted trim"),
        ("restricted_source", "TEXT", "How it is marked: shaded row or a numbered footnote"),
        ("attributes_json", "TEXT", "Every row-key cell as printed, as JSON {column header: value}"),
        ("warnings", "INTEGER", "Number of validation warnings on this configuration (catalog_flag, severity warning/error)"),
    ]),
    "valve_config_size": ("Body sizes a configuration applies to (a size cell can name several, e.g. '2 & 3 x 2').", [
        ("config_id", "TEXT", "valve_config.config_id"),
        ("nps", "REAL", "Nominal pipe size, inches (DN columns converted)"),
    ]),
    "flow_coefficient": ("Every printed flow coefficient value from Catalog 12.", [
        ("config_id", "TEXT", "valve_config.config_id"),
        ("coefficient", "TEXT", "Cv, Kv, XT, FL, Fd, Kc, Kn, Cvnet, Kvnet, FLnet, XTnet, HoleType"),
        ("position_basis", "TEXT", "'pct_travel', 'deg_rotation', 'relative_flow_coefficient', or 'single'"),
        ("position", "REAL", "Opening: % of travel or degrees of rotation; NULL for single values"),
        ("position_label", "TEXT", "For single values: the column header, e.g. 'FL (3)', 'Coeffs for 6 mm Travel'"),
        ("value", "REAL", "Value; NULL where the catalog prints '---'"),
        ("value_raw", "TEXT", "Cell exactly as printed"),
        ("footnotes", "TEXT", "Footnote numbers on the cell, comma-separated (see page_note)"),
    ]),
    "catalog_flag": ("Validation results on Catalog 12 values: catalog errors are flagged, never corrected.", [
        ("config_id", "TEXT", "valve_config.config_id"),
        ("coefficient", "TEXT", "Coefficient checked"),
        ("position", "TEXT", "Opening or column label"),
        ("check_name", "TEXT", "kv_cv_mismatch, out_of_range, cv_decreasing, parse_error"),
        ("severity", "TEXT", "error, warning, info"),
        ("detail", "TEXT", "What was found"),
    ]),
    "alias": ("Catalog 12 statements that a valve uses another valve's coefficients.", [
        ("valve", "TEXT", "Valve the statement is about, e.g. 'EDR'"),
        ("uses", "TEXT", "Family whose tables apply, or 'external' for another document"),
        ("pdf_pages", "TEXT", "PDF pages that apply, space-separated; empty = the whole family or as stated"),
        ("condition", "TEXT", "Limits stated with it (sizes, classes, flow direction)"),
        ("source_label", "TEXT", "Printed page label of the statement"),
        ("source_text", "TEXT", "The statement"),
    ]),
    "page_note": ("Footnotes and notes printed on Catalog 12 coefficient pages.", [
        ("catalog", "TEXT", "'C12'"),
        ("pdf_page", "INTEGER", "PDF page"),
        ("printed_label", "TEXT", "Printed page label"),
        ("note", "TEXT", "Footnote number, or 'note'"),
        ("text", "TEXT", "Text as printed"),
    ]),
    "actuator_rating": ("Catalog 14 pressure drop method: one maximum allowable pressure drop for one valve + actuator construction.", [
        ("rating_id", "TEXT PRIMARY KEY", "Stable id 'C14-<pdf page>-<n>'"),
        ("catalog", "TEXT", "'C14'"),
        ("section", "TEXT", "'A' (sliding-stem) or 'C' (rotary)"),
        ("motion", "TEXT", "'sliding-stem' or 'rotary'"),
        ("pdf_page", "INTEGER", "PDF page"),
        ("printed_label", "TEXT", "Printed page label"),
        ("actuator", "TEXT", "Actuator type: 585C, 657, 667, 1052, 1061, 2052, FieldQ"),
        ("actuator_size", "TEXT", "Actuator size as printed (row key in section A, column header in section C)"),
        ("valve", "TEXT", "Rotary: valve as printed in the heading, e.g. 'A11, CL600', 'V150, V200, V300'"),
        ("valve_nps", "REAL", "Rotary: valve size, NPS"),
        ("shaft_in", "REAL", "Rotary tables listed by shaft size: shaft diameter, inches"),
        ("angle_deg", "REAL", "Rotary: angle of opening, degrees (0 = closed)"),
        ("port_in", "REAL", "Sliding-stem: port diameter, inches"),
        ("travel_in", "REAL", "Sliding-stem: valve travel, inches"),
        ("yoke_boss", "TEXT", "Sliding-stem: yoke boss size, inches, as printed (e.g. '3-9/16')"),
        ("balance", "TEXT", "Sliding-stem: Balanced or Unbalanced valve body"),
        ("leakage", "TEXT", "Shutoff class where stated, e.g. 'Class IV'"),
        ("action", "TEXT", "Push-Down-To-Open/Close, Spring-To-Open/Close, where stated"),
        ("flow", "TEXT", "Forward Flow or Reverse Flow, where stated"),
        ("supply", "TEXT", "Air supply as printed: psig for pistons, supply range for diaphragms, e.g. '60', '0-33'"),
        ("bench_set", "TEXT", "Spring-and-diaphragm bench set range, psig, e.g. '6-30'"),
        ("spring", "TEXT", "Rotary: spring part number or initial compression, where printed"),
        ("condition", "TEXT", "The full column header path the value sits under, as printed"),
        ("column_heading", "TEXT", "Header text shared by all value columns of the table"),
        ("row_group", "TEXT", "Row-group label, e.g. '2.5 Inch Port', 'Push-Down-To-Open'"),
        ("keys_json", "TEXT", "Row-key cells as printed, as JSON"),
        ("max_dp", "REAL", "Maximum allowable pressure drop"),
        ("unit", "TEXT", "'psi' or 'bar' (rotary tables print both; each is its own row)"),
        ("footnotes", "TEXT", "Footnote numbers on the cell"),
        ("confirmed", "INTEGER", "1 if a second PDF reader found the row's values in the same order"),
    ]),
    "valve_actuator_link": ("Which Catalog 14 ratings apply to which Catalog 12 configuration (matching rules in fisher/integrate.py).", [
        ("config_id", "TEXT", "valve_config.config_id"),
        ("rating_id", "TEXT", "actuator_rating.rating_id"),
        ("match_basis", "TEXT", "'port+travel+balance' (sliding-stem) or 'valve+nps' (rotary)"),
    ]),
    "valve_actuator_coverage": ("For every configuration: whether it links to Catalog 14, and if not, why.", [
        ("config_id", "TEXT PRIMARY KEY", "valve_config.config_id"),
        ("method", "TEXT", "'sliding-stem' or 'rotary'"),
        ("c14_valve", "TEXT", "C14 valve code or family matched"),
        ("ratings", "INTEGER", "Number of linked ratings (psi rows)"),
        ("max_rated_dp_psi", "REAL", "Highest maximum allowable pressure drop among the links, psi"),
        ("note", "TEXT", "Why there are no links, when there are none"),
    ]),
    "reference_table": ("Every other table, kept as printed: C12 sections 2-3 and all C14 tables (including force and torque methods).", [
        ("table_id", "TEXT PRIMARY KEY", "Stable id"),
        ("catalog", "TEXT", "'C12' or 'C14'"),
        ("section", "TEXT", "Catalog section"),
        ("pdf_page", "INTEGER", "PDF page"),
        ("printed_label", "TEXT", "Printed page label"),
        ("title", "TEXT", "Table title as printed, if any"),
        ("heading", "TEXT", "C14: page heading"),
        ("n_rows", "INTEGER", "Data rows"),
        ("n_cols", "INTEGER", "Columns"),
        ("rows_confirmed", "INTEGER", "Rows a second PDF reader found in the same order"),
    ]),
    "reference_cell": ("Cells of reference_table, one row per cell.", [
        ("table_id", "TEXT", "reference_table.table_id"),
        ("row", "INTEGER", "0-based data row"),
        ("col", "INTEGER", "0-based column"),
        ("header", "TEXT", "Column header path as printed"),
        ("value", "TEXT", "Cell as printed"),
    ]),
    "steam_saturated": ("Saturated steam, Catalog 12 pages 2-33/2-34.", [
        ("psia", "REAL", "Vapor pressure, psia"),
        ("temp_f", "REAL", "Temperature, deg F"),
        ("steam_density_lb_ft3", "REAL", "Saturated steam density, lb/ft3"),
        ("water_specific_gravity", "REAL", "Water specific gravity at that temperature"),
        ("printed_label", "TEXT", "Printed page label"),
    ]),
    "equation_constant": ("Numerical constants for the sizing equations, Catalog 12 Table 2 (page 2-3).", [
        ("name", "TEXT", "N1, N2, N4, N5, N6, N7, N8, N9"),
        ("units", "TEXT", "Unit set the value applies to"),
        ("value", "REAL", "Constant"),
    ]),
    "leakage_class": ("ANSI/FCI 70-2 seat leakage classes, Catalog 12 page 2-28.", [
        ("class", "TEXT PRIMARY KEY", "II, III, IV, V, VI"),
        ("maximum_leakage", "TEXT", "As printed"),
        ("fraction_of_rated_capacity", "REAL", "Classes II-IV"),
        ("test_medium", "TEXT", "Air or water"),
        ("test_conditions", "TEXT", "As printed"),
    ]),
    "leakage_class_vi": ("Class VI allowable leakage by nominal port diameter, Catalog 12 page 2-28.", [
        ("port_diameter_in", "TEXT", "As printed, e.g. '1-1/2'"),
        ("port_diameter_mm", "REAL", "mm"),
        ("bubbles_per_minute", "REAL", "Bubbles per minute"),
        ("ml_per_minute", "REAL", "mL per minute"),
    ]),
    "chart_fit": ("Catalog 12 Section 3 noise charts digitized as straight lines: y = slope * log10(x) + intercept. APPROXIMATE.", [
        ("term", "TEXT PRIMARY KEY", "SPL_dP_cavitating, SPL_dP_noncavitating, dSPL_Cv, dSPL_Km, dSPL_G"),
        ("printed_label", "TEXT", "Printed page label of the chart"),
        ("x", "TEXT", "What x is"),
        ("slope", "REAL", "dB per decade"),
        ("intercept", "REAL", "dB"),
        ("x_min", "REAL", "Chart range, lower"),
        ("x_max", "REAL", "Chart range, upper"),
        ("scatter_db", "REAL", "Standard deviation of chart pixels about the line, dB"),
    ]),
    "chart_point": ("Catalog 12 page 2-30 liquid-gas mixture charts sampled as points. APPROXIMATE.", [
        ("chart", "TEXT", "'two_phase_fm' (Fm vs Vr) or 'two_phase_critical_dp_ratio' (dP/P1 vs C1)"),
        ("x", "REAL", "Vr or C1"),
        ("y", "REAL", "Fm or dP/P1"),
    ]),
    "force_port_data": ("Catalog 14 force method: port geometry (Tables 2, 2C-2H, pages B-4 to B-9).", [
        ("source_table", "TEXT", "Catalog table: 2, 2C, 2D, 2E, 2F, 2G, '2H TBX & CVX', '2H NotchFlo DST'"),
        ("scope", "TEXT", "Valves the table covers, where stated for the whole table"),
        ("valve", "TEXT", "Valve rating/design the row applies to (per-valve tables)"),
        ("nps", "TEXT", "Valve size as printed (per-valve tables)"),
        ("port_in", "REAL", "Port diameter, inches"),
        ("circumference_in", "REAL", "Port circumference, inches (PC in the seat load equations)"),
        ("area_in2", "REAL", "Port area, square inches (Tables 2/2C)"),
        ("unbalance_area_in2", "REAL", "Unbalance area, square inches (per-valve tables; Tables 2/2C use force_unbalance_area)"),
        ("stem_in", "REAL", "Stem diameter, inches (TBX/CVX)"),
        ("printed_label", "TEXT", "Printed page label"),
    ]),
    "force_unbalance_area": ("Catalog 14 Tables 2/2C unbalance areas for balanced plugs, one row per construction listed.", [
        ("source_table", "TEXT", "2 or 2C"),
        ("port_in", "REAL", "Port diameter, inches"),
        ("unbalance_area_in2", "REAL", "Unbalance area, square inches"),
        ("applies_to", "TEXT", "Valves / constructions the area applies to, as printed"),
        ("printed_label", "TEXT", "Printed page label"),
    ]),
    "force_stem_area": ("Catalog 14 Table 3: valve stem area (page B-11).", [
        ("stem_in", "REAL", "Stem diameter, inches"),
        ("stem_text", "TEXT", "As printed, e.g. '1-1/4'"),
        ("area_in2", "REAL", "Stem area, square inches"),
        ("printed_label", "TEXT", "Printed page label"),
    ]),
    "force_seat_load_rule": ("Catalog 14 Table 4: seat load equation by valve type, construction, port size and leak class (pages B-12/B-13).", [
        ("valve_type", "TEXT", "Valve types the rule covers, as printed"),
        ("construction", "TEXT", "Seat construction"),
        ("port_size", "TEXT", "Port size range, as printed ('All', '4.375 or Less', ...)"),
        ("class_standard", "TEXT", "Standard leak class"),
        ("equation_standard", "TEXT", "Seat load equation (PC = port circumference, in; Pshutoff = dP at shutoff, psi; A, B from force_seat_factor)"),
        ("class_optional", "TEXT", "Optional leak class"),
        ("equation_optional", "TEXT", "Seat load equation for the optional class"),
        ("printed_label", "TEXT", "Printed page label"),
    ]),
    "force_seat_factor": ("Catalog 14 Table 5: A and B factors for composition seats (page B-14).", [
        ("valves", "TEXT", "'EZ Valves' or 'All Other Valves'"),
        ("port_in", "REAL", "Port diameter, inches"),
        ("seat", "TEXT", "Seat material"),
        ("flow", "TEXT", "Flow direction"),
        ("a", "REAL", "A factor (seat load = A x dP shutoff + B, lb)"),
        ("b", "REAL", "B factor, lb"),
        ("printed_label", "TEXT", "Printed page label"),
    ]),
    "force_packing_friction": ("Catalog 14 Tables 6, 6A-6D: packing friction (pages B-16 to B-18).", [
        ("source_table", "TEXT", "6, 6A, 6B, 6C, 6D"),
        ("packing", "TEXT", "Packing arrangement"),
        ("stem_in", "REAL", "Stem diameter, inches"),
        ("pressure_class", "TEXT", "Valve pressure class as printed ('All', '600', 'Up to CL600', ...)"),
        ("pounds", "REAL", "Friction force, lb"),
        ("printed_label", "TEXT", "Printed page label"),
    ]),
    "diaphragm_actuator_force": ("Catalog 14 657, 657R, 667 'Available Actuator Force' pages (B-31 to B-72).", [
        ("actuator", "TEXT", "657, 657R or 667"),
        ("size", "TEXT", "Actuator size as printed"),
        ("supply", "TEXT", "Diaphragm pressure range, psig ('0-18', '0-33', ...)"),
        ("travel_in", "REAL", "Valve travel, inches"),
        ("spring", "TEXT", "Spring part number"),
        ("spring_rate_lb_in", "REAL", "Spring rate, lb/in"),
        ("force_lb", "REAL", "Available actuator force, lb"),
        ("bench_set", "TEXT", "Bench set, psig"),
        ("printed_label", "TEXT", "Printed page label"),
    ]),
    "torque_characteristic": ("Catalog 14 torque method Table 1: A, B, C factors and shaft limit (so far the 7600 butterfly, pages D-5/D-6).", [
        ("valve", "TEXT", "Valve"),
        ("nps", "TEXT", "Valve size, NPS"),
        ("shaft_in", "TEXT", "Shaft diameter, inches, as printed"),
        ("shaft_class", "TEXT", "Shaft class"),
        ("bearing", "TEXT", "Bearing material"),
        ("a", "REAL", "A factor: TB = A x dP shutoff + B (lbf-in)"),
        ("b", "REAL", "B factor, lbf-in"),
        ("c_60", "REAL", "C factor at 60 deg maximum rotation: TD = C x dP eff"),
        ("c_90", "REAL", "C factor at 90 deg maximum rotation"),
        ("max_torque_lbf_in", "REAL", "Maximum allowable shaft torque, lbf-in (S17400 to 300 F)"),
        ("printed_label", "TEXT", "Printed page label"),
    ]),
    "c14_table_value": ("Every numeric (and placeholder) cell of the Catalog 14 force (B) and torque (D) method tables, typed, with its row keys and column header path. Built by extract/catalog14_values.py.", [
        ("table_id", "TEXT", "reference_table.table_id of the same table as printed"),
        ("printed_label", "TEXT", "Printed page label"),
        ("pdf_page", "INTEGER", "PDF page"),
        ("section", "TEXT", "'B' (force method) or 'D' (torque method)"),
        ("table_no", "INTEGER", "Table position on the page, from 1"),
        ("heading", "TEXT", "Page heading (actuator, valve, construction, as printed)"),
        ("row_group", "TEXT", "Row-group or table label above the row, e.g. '0-18 Psig to Diaphragm', 'Spline Shaft'"),
        ("row_no", "INTEGER", "Data row within the table, from 1"),
        ("keys", "TEXT", "JSON object of the row's key columns (size, shaft, class, spring ...), merged cells carried down"),
        ("column_path", "TEXT", "Column header path, group headers joined with ' › '"),
        ("value", "REAL", "Number; NULL for placeholders"),
        ("value_raw", "TEXT", "Cell as printed ('---', 'CF', '207 (3-15)', '1424(1)')"),
        ("footnotes", "TEXT", "Footnote numbers attached to the value"),
        ("confirmed", "TEXT", "Second reader: 'line' = row's numbers in order on one pdftotext line; 'window' = all within four consecutive lines (vertically centred or merged cells); 'page' = the row's only numbers are merged-cell values, found on the page but not tied to a line; '' = not found. A repeated merged value carries the result of the row where it is printed"),
        ("merged", "INTEGER", "1 = printed once in a cell merged over several rows (or beside a stack of lines) and repeated here"),
        ("caption", "TEXT", "The line of text just above the table, as printed (often its title)"),
    ]),
    "torque_factor": ("Catalog 14 torque method factors for every rotary valve (section D), classified from c14_table_value by extract/catalog14_torque_factors.py.", [
        ("valve", "TEXT", "Valve, from the catalog's table of contents (e.g. 8532, A11, V150/V200/V300, Control-Disk)"),
        ("variant", "TEXT", "Qualifier from the page heading (e.g. 'with Attenuator', 'Novex Seal', 'Full Bore')"),
        ("pressure_class", "TEXT", "Pressure class from the table title or page heading"),
        ("flow", "TEXT", "forward, reverse, normal, 'forward and reverse', or '' where not printed"),
        ("construction", "TEXT", "Seal / packing / bearing row group as printed"),
        ("nps", "TEXT", "Valve size as printed (may be a range such as '14-24' for K values)"),
        ("shaft", "TEXT", "Shaft diameter as printed (keyed / spline variants labelled)"),
        ("factor", "TEXT", "A, B (TB = A dP shutoff + B); C (TD = C dP eff); K (gas dP eff = K P1 abs); MAST (max allowable shaft torque); STRENGTH (percent of MAST by temperature); E, F, SF, FF (SIS); BREAK, RUN, MARGIN (Z500); VRUN, VETC, VBTO and MAST_* (30,000 operating torques); MULTIPLIER (U valve); other"),
        ("angle_deg", "REAL", "Angle of rotation for C and K"),
        ("qualifier", "TEXT", "Rest of the column path: seal material for B, shaft material or bearing for MAST, temperature range for STRENGTH, pressure range for A ..."),
        ("torque_direction", "TEXT", "For C: 'tends to close' (kappa mark) or 'tends to open' (theta mark) where printed"),
        ("other_keys", "TEXT", "JSON of any other row keys"),
        ("value", "REAL", "Value (A dimensionless in-lbf/psi; B, MAST, torques lbf-in)"),
        ("value_raw", "TEXT", "As printed"),
        ("table_title", "TEXT", "Table title where printed"),
        ("printed_label", "TEXT", "Printed page label"),
        ("pdf_page", "INTEGER", "PDF page"),
        ("table_no", "INTEGER", "Table position on the page"),
        ("row_no", "INTEGER", "Row within the table (factors of one printed row share it)"),
        ("column_path", "TEXT", "Column header path as printed"),
        ("confirmed", "TEXT", "Second-reader result for the row (see c14_table_value)"),
        ("merged", "INTEGER", "1 = value repeated from a merged cell"),
    ]),
}

VIEWS = {
    "v_valve_actuator": ("Catalog 12 configurations joined to the Catalog 14 ratings that apply to them.", """
        SELECT c.config_id, c.family, c.motion, c.nps_text, c.port_in, c.travel_in, c.characteristic,
               c.flow_direction, c.rated_cv, c.printed_label AS valve_page,
               r.rating_id, r.actuator, r.actuator_size, r.angle_deg, r.supply, r.bench_set, r.leakage,
               r.action, r.flow, r.condition, r.max_dp, r.unit, r.printed_label AS actuator_page
        FROM valve_actuator_link l
        JOIN valve_config c ON c.config_id = l.config_id
        JOIN actuator_rating r ON r.rating_id = l.rating_id"""),
    "v_cv_curve": ("Cv against opening for every configuration (non-null values only).", """
        SELECT f.config_id, c.family, c.nps_text, c.motion, f.position_basis, f.position, f.value AS cv
        FROM flow_coefficient f JOIN valve_config c ON c.config_id = f.config_id
        WHERE f.coefficient = 'Cv' AND f.position IS NOT NULL AND f.value IS NOT NULL"""),
}


def rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def num(v):
    try:
        return float(v) if v not in ("", None) else None
    except ValueError:
        return None


def parse_condition(section: str, cond: str, column_heading: str) -> tuple[str, str, str, str]:
    """(actuator_size, supply, bench_set, spring) from a Catalog 14 column header path.

    The shared column heading (e.g. "Actuator Size, Air to Diaphragm, and Spring Part Number › SIZE 70")
    and the column's own path (e.g. "0-33 › 3") are read together.
    """
    ctx = f"{column_heading} › {cond}"
    size = supply = bench = spring = ""
    m = re.search(r"(?:\bSize|\bSIZE)\s*(\d+)|\bQ\s*(\d+)", ctx)
    if m:
        size = m.group(1) or m.group(2)
    m = re.search(r"Air to (?:Cylinder|Diaphragm),?\s*(?:Psig\s+)?([\d\-]+)", cond)  # A-6 omits "Psig"
    if m:
        supply = m.group(1)
    m = re.search(r"Bench Set,\s*Psig\s+([\d\-]+)", cond)
    if m:
        bench = m.group(1)
    if section == "C" and not supply:
        parts = [p.strip() for p in cond.split("›")]
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:ps?ig|barg\s*/\s*(\d+)\s*psig)", cond, re.I)  # "Pig": sic, C-40
        if m:
            supply = m.group(2) or m.group(1) if "barg" in m.group(0).lower() else m.group(1)
        elif re.search(r"Air to Diaphragm|Cylinder Pressure|Supply", ctx, re.I):
            # The first plain number or range in the column's own path is the supply.
            supply = next((p for p in parts if re.fullmatch(r"\d+(?:\.\d+)?(?:-\d+)?", p)), "")
    if section == "C":
        parts_no = [re.sub(r"\s", "", x) for x in re.findall(r"\b\d[A-Z]\d{4}\s?\d{5}\b", ctx)]
        comp = re.findall(r"(\d+(?:\.\d+)?)\s*psig", cond, re.I)
        spring = " ".join(dict.fromkeys(parts_no)) + (f" initial compression {comp[1]} psig" if len(comp) > 1 else "")
    return size, supply, bench, spring.strip()


def build(db_path: str, doc_path: str) -> None:
    db = Path(db_path)
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    for table, (_, cols) in SCHEMA.items():
        con.execute(f"CREATE TABLE {table} ({', '.join(f'{c} {t}' for c, t, _ in cols)})")
    ins = lambda t, recs: con.executemany(  # noqa: E731
        f"INSERT INTO {t} VALUES ({', '.join('?' * len(SCHEMA[t][1]))})", recs)

    ins("source", [
        ("C12", "Fisher Catalog 12, ASME/ISA/IEC Valve Sizing", "D103182X012", "April 2022",
         "c40ea5fe30368b6e9f24e13d2a822425e62f361a3b2a27935cafafa510acf355",
         "https://www.emerson.com/is/content/emerson/en/final-control/flow-controls/documents/d103182x012.pdf"),
        ("C14", "Fisher Catalog 14, Actuator Sizing", "D103428X012", "2018-2021 pages",
         "869ca15dfa76a710d0048ef45f022fe99a9ea278ee4acde67c02207c692e542e",
         "https://www.emerson.com/is/content/emerson/en/final-control/flow-controls/documents/d103428x012.pdf"),
    ])

    # Pages
    inv = rows(ROOT / "docs" / "page_inventory.csv")
    ins("page", [("C12", int(r["pdf_page"]), r["printed_label"], r["section"].split()[0], r["valve_family"],
                  r["page_kind"], "") for r in inv])
    c14_pages = {}
    for r in rows(DATA / "catalog14" / "index.csv"):
        c14_pages.setdefault(int(r["page"]), (r["printed_label"], r["section"], r["heading"]))
    for r in rows(DATA / "catalog14" / "pages.csv"):
        c14_pages[int(r["page"])] = (r["printed_label"], r["section"], r["heading"])
    ins("page", [("C14", p, lab, sec, "", "", head) for p, (lab, sec, head) in sorted(c14_pages.items())])

    # Valve configurations
    cat = Catalog.load()
    configs = [c for c in cat.configs.values()]
    motion = {c.config_id: ("rotary" if c.position_basis == "deg_rotation" else "sliding-stem") for c in configs}
    cfg_rows, size_rows = [], []
    for c in configs:
        fl_single = next((v for (k, _), v in c.singles.items() if k == "FL"), None)
        cfg_rows.append((
            c.config_id, c.family, motion[c.config_id], "C12", c.page, c.printed_label,
            " | ".join(x for x in (c.page_title, c.table_title, c.section) if x), c.characteristic,
            c.flow_direction, c.nps, integrate._inches(c, "port") if motion[c.config_id] == "sliding-stem" else None,
            integrate._inches(c, "travel") if motion[c.config_id] == "sliding-stem" else None,
            c.position_basis, c.rated("Cv"), c.rated("XT"), fl_single, int(c.restricted), c.restricted_source,
            json.dumps(c.attrs, ensure_ascii=False), sum(1 for f in c.flags if f["severity"] != "info")))
        size_rows += [(c.config_id, s) for s in c.sizes]
    ins("valve_config", cfg_rows)
    ins("valve_config_size", size_rows)

    ins("flow_coefficient", [(v["config_id"], v["coefficient"], v["position_basis"], num(v["position"]),
                              v["position_label"], num(v["value"]), v["value_raw"], v["footnotes"])
                             for v in rows(DATA / "coefficients.csv")])
    ins("catalog_flag", [(f["config_id"], f["coefficient"], f["position"], f["check"], f["severity"], f["detail"])
                         for f in rows(DATA / "flags.csv")])
    page_by_label = {r["printed_label"]: r["pdf_page"] for r in inv}
    ins("alias", [(a["valve"], a["uses"], a["pages"].replace(";", " "), a["condition"], a["source_label"],
                   a["source_text"]) for a in rows(DATA / "aliases.csv")])
    ins("page_note", [("C12", int(n["page"]), n["printed_label"], n["note"], n["text"])
                      for n in rows(DATA / "page_notes.csv")])

    # Actuator ratings
    rating_id, counter, rat_rows = {}, {}, []
    for r in actuators.ratings():
        counter[r.page] = counter.get(r.page, 0) + 1
        rid = f"C14-{r.page}-{counter[r.page]}"
        rating_id[id(r)] = rid
        size, supply, bench, spring = parse_condition(r.section, r.column, r.column_heading)
        size = r.actuator_size or size
        rat_rows.append((
            rid, "C14", r.section, "sliding-stem" if r.section == "A" else "rotary", r.page, r.printed_label,
            r.actuator, size, r.valve, r.valve_nps, r.shaft_in, r.angle_deg, r.port_in, r.travel_in,
            next((v for k, v in r.keys.items() if "yoke" in k.lower()), ""), r.balance, r.leakage, r.action, r.flow,
            supply, bench, spring, r.column, r.column_heading, r.group, json.dumps(r.keys, ensure_ascii=False),
            r.value, r.unit, r.footnotes, int(r.confirmed)))
    ins("actuator_rating", rat_rows)

    # Links
    link_rows, cov_rows = [], []
    for c in configs:
        if not c.curves or c.family == "Fd Style Modifiers":
            continue
        m = integrate.actuators_for_config(c)
        basis = "valve+nps" if m.method == "rotary" else "port+travel+balance"
        link_rows += [(c.config_id, rating_id[id(r)], basis) for r in m.ratings]
        cov_rows.append((c.config_id, m.method, (m.matched_on or {}).get("valve") or "",
                         len(m.ratings), max((r.value for r in m.ratings), default=None), m.note))
    ins("valve_actuator_link", link_rows)
    ins("valve_actuator_coverage", cov_rows)

    # Families
    fam_rows = []
    for fam in sorted({c.family for c in configs}):
        fc = [c for c in configs if c.family == fam]
        mot = max({"rotary", "sliding-stem"}, key=lambda m: sum(motion[c.config_id] == m for c in fc))
        codes = sorted({code for c in fc for code in integrate.sliding_valve_codes(c)})
        bal = sorted({integrate.SLIDING_COVERAGE[code][0] for code in codes})
        linked = sum(1 for r in cov_rows if r[3] and cat.get(r[0]).family == fam)
        labels = sorted({c.printed_label for c in fc})
        fam_rows.append((fam, mot, len(fc), " ".join(labels), " ".join(codes), "/".join(bal), linked))
    ins("valve_family", fam_rows)

    # Reference tables (C12 sections 2-3, all of C14)
    ref_rows, cell_rows = [], []
    for t in reference.tables():
        headers, data = reference.table(t["id"])
        ref_rows.append((t["id"], "C12", t["printed_label"].split("-")[0], int(t["page"]), t["printed_label"],
                         t["title"], "", int(t["rows"]), int(t["columns"]), int(t["rows_confirmed"])))
        cell_rows += [(t["id"], i, j, headers[j] if j < len(headers) else "", v)
                      for i, row in enumerate(data) for j, v in enumerate(row) if v != ""]
    for t in actuators.tables():
        headers, data = actuators.table(t["id"])
        ref_rows.append((t["id"], "C14", t["section"], int(t["page"]), t["printed_label"], t["title"], t["heading"],
                         int(t["rows"]), int(t["columns"]), int(t["rows_confirmed"])))
        cell_rows += [(t["id"], i, j, headers[j] if j < len(headers) else "", v)
                      for i, row in enumerate(data) for j, v in enumerate(row) if v != ""]
    ins("reference_table", ref_rows)
    ins("reference_cell", cell_rows)

    ref = DATA / "reference"
    ins("steam_saturated", [(float(r["psia"]), float(r["temp_f"]), float(r["steam_density_lb_ft3"]),
                             float(r["water_specific_gravity"]), r["page"]) for r in rows(ref / "saturated_steam.csv")])
    ins("equation_constant", [(n, u, v) for n, d in sizing.N.items() for u, v in d.items()])
    ins("leakage_class", [(r["class"], r["maximum_leakage"], num(r["fraction_of_rated_capacity"]), r["test_medium"],
                           r["test_conditions"]) for r in rows(ref / "leakage_classes.csv")])
    ins("leakage_class_vi", [(r["port_diameter_in"], float(r["port_diameter_mm"]), float(r["bubbles_per_minute"]),
                              float(r["ml_per_minute"])) for r in rows(ref / "leakage_class_vi.csv")])
    ins("chart_fit", [(r["term"], r["page"], r["x"], float(r["slope"]), float(r["intercept"]), float(r["x_min"]),
                       float(r["x_max"]), float(r["scatter_db"])) for r in rows(ref / "noise_chart_fits.csv")])
    ins("chart_point", [("two_phase_fm", float(r["vr"]), float(r["fm"])) for r in rows(ref / "two_phase_fm.csv")] +
        [("two_phase_critical_dp_ratio", float(r["c1"]), float(r["dp_over_p1"]))
         for r in rows(ref / "two_phase_critical_dp_ratio.csv")])

    fd = DATA / "catalog14" / "force"
    ins("force_port_data", [(r["table"], r["scope"], r["valve"], r["nps"], num(r["port_in"]), num(r["circumference_in"]),
                             num(r["area_in2"]), num(r["unbalance_area_in2"]), num(r["stem_in"]), r["printed_label"])
                            for r in rows(fd / "port_data.csv")])
    ins("force_unbalance_area", [(r["table"], num(r["port_in"]), num(r["unbalance_area_in2"]), r["applies_to"],
                                  r["printed_label"]) for r in rows(fd / "unbalance_area.csv")])
    ins("force_stem_area", [(num(r["stem_in"]), r["stem_text"], num(r["area_in2"]), r["printed_label"])
                            for r in rows(fd / "stem_area.csv")])
    ins("force_seat_load_rule", [(r["type"], r["construction"], r["port_size"], r["class_standard"], r["equation_standard"],
                                  r["class_optional"], r["equation_optional"], r["printed_label"])
                                 for r in rows(fd / "seat_load_rules.csv")])
    ins("force_seat_factor", [(r["valves"], num(r["port_in"]), r["seat"], r["flow"], num(r["A"]), num(r["B"]),
                               r["printed_label"]) for r in rows(fd / "seat_factors.csv")])
    ins("force_packing_friction", [(r["table"], r["packing"], num(r["stem_in"]), r["pressure_class"], num(r["pounds"]),
                                    r["printed_label"]) for r in rows(fd / "packing_friction.csv")])
    ins("diaphragm_actuator_force", [(r["actuator"], r["size"], r["supply"], num(r["travel_in"]), r["spring"],
                                      num(r["spring_rate_lb_in"]), num(r["force_lb"]), r["bench_set"], r["printed_label"])
                                     for r in rows(fd / "diaphragm_force.csv")])
    ins("torque_characteristic", [(r["valve"], r["nps"], r["shaft_in"], r["shaft_class"], r["bearing"], num(r["A"]),
                                   num(r["B"]), num(r["C_60"]), num(r["C_90"]), num(r["max_torque_lbf_in"]),
                                   r["printed_label"]) for r in rows(DATA / "catalog14" / "torque" / "torque_characteristics.csv")])

    c14_ids = {}
    for t in rows(DATA / "catalog14" / "index.csv"):
        m = re.match(r"(.+?_t\d+)(_|$)", t["id"])
        c14_ids[(t["page"], m.group(1))] = t["id"]
    tv = []
    for r in rows(DATA / "catalog14" / "table_values.csv"):
        prefix = f"{r['printed_label'].replace('-', '_').replace('.', '_')}_t{r['table']}"
        tv.append((c14_ids.get((r["page"], prefix), ""), r["printed_label"], int(r["page"]), r["section"],
                   int(r["table"]), r["heading"], r["group"], int(r["row"]), r["keys"], r["column"], num(r["value"]),
                   r["value_raw"], r["footnotes"], r["confirmed"], int(r["merged"]), r["caption"]))
    ins("c14_table_value", tv)
    ins("torque_factor", [(r["valve"], r["variant"], r["pressure_class"], r["flow"], r["construction"], r["nps"],
                           r["shaft"], r["factor"], num(r["angle_deg"]), r["qualifier"], r["torque_direction"],
                           r["other_keys"], num(r["value"]), r["value_raw"], r["table_title"], r["printed_label"],
                           int(r["page"]), int(r["table_no"]), int(r["row_no"]), r["column_path"], r["confirmed"],
                           int(r["merged"])) for r in rows(DATA / "catalog14" / "torque" / "torque_factors.csv")])

    for name, (_, sql) in VIEWS.items():
        con.execute(f"CREATE VIEW {name} AS {sql}")
    for stmt in ("CREATE INDEX ix_fc_config ON flow_coefficient(config_id)",
                 "CREATE INDEX ix_size ON valve_config_size(nps, config_id)",
                 "CREATE INDEX ix_cfg_family ON valve_config(family)",
                 "CREATE INDEX ix_rating_valve ON actuator_rating(section, valve_nps, angle_deg)",
                 "CREATE INDEX ix_rating_port ON actuator_rating(section, port_in, travel_in)",
                 "CREATE INDEX ix_link_config ON valve_actuator_link(config_id)",
                 "CREATE INDEX ix_cell ON reference_cell(table_id)",
                 "CREATE INDEX ix_flag ON catalog_flag(config_id)",
                 "CREATE INDEX ix_c14_value ON c14_table_value(printed_label, table_no)",
                 "CREATE INDEX ix_torque_factor ON torque_factor(valve, nps, factor)"):
        con.execute(stmt)
    con.commit()
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in SCHEMA}
    con.execute("VACUUM")
    con.close()
    write_doc(doc_path, counts)
    print(f"{db_path}: " + ", ".join(f"{t} {n}" for t, n in counts.items()))


def write_doc(path: str, counts: dict) -> None:
    out = ["# Unified data model", "",
           "`data/fisher.db` (SQLite) holds everything extracted from Fisher Catalog 12 (valve sizing) and "
           "Catalog 14 (actuator sizing) in one schema. It is generated by `extract/build_db.py`; this page is "
           "generated from the same schema definition, so it always matches the database.", "",
           "Conventions:", "",
           "- **Provenance on every row:** `catalog` ('C12' or 'C14'), `pdf_page` and `printed_label` say where a value is printed.",
           "- **Fixed units:** sizes are NPS in inches, dimensions are inches (`_in`), angles are degrees (`_deg`) and pressure drops are psi unless a `unit` column says otherwise.",
           "- **As printed:** `*_raw`, `*_text` and `*_json` columns keep the original text. Parsed columns are for filtering.",
           "- **Errors are kept:** values the catalog prints wrongly are kept and flagged in `catalog_flag`, never corrected.",
           "- **APPROXIMATE data** (digitized charts) is labelled in the table description.", "",
           "Start with the views:", ""]
    for name, (desc, _) in VIEWS.items():
        out.append(f"- `{name}`: {desc}")
    out += ["", "```sql", "-- Actuators rated for ES NPS 3 equal percentage (config 152-1-8) at 300 psi or more",
            "SELECT actuator, actuator_size, condition, max_dp, actuator_page",
            "FROM v_valve_actuator WHERE config_id = '152-1-8' AND unit = 'psi' AND max_dp >= 300;", "```", ""]
    for table, (desc, cols) in SCHEMA.items():
        out += [f"## `{table}`", "", f"{desc} ({counts.get(table, 0):,} rows)", "",
                "| Column | Type | Meaning |", "|---|---|---|"]
        out += [f"| `{c}` | {t.split()[0]} | {d} |" for c, t, d in cols]
        out.append("")
    Path(path).write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    build(*sys.argv[1:])
