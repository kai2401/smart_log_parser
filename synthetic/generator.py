"""
Synthetic semiconductor tool log generator.
Produces realistic logs in JSON, CSV, XML, Syslog, and plain text formats.
Row count is randomly chosen between 1 000 and 5 000 per run.
"""

import json
import random
import datetime
import os
import xml.etree.ElementTree as ET
from xml.dom import minidom

# ── Random seed: different every run ────────────────────────────────────────
SEED = random.randint(0, 10_000)
random.seed(SEED)
print(f"  seed={SEED}")

TOOLS = [
    "ETCH-01",
    "ETCH-02",
    "CVD-03",
    "PVD-04",
    "CMP-05",
    "LITHO-06",
    "IMP-07",
    "ANNEAL-08",
]
RECIPES = [
    "ETH_SiO2_v3",
    "CVD_TiN_v2",
    "PVD_Al_v1",
    "CMP_Cu_v4",
    "LITHO_DUV_v5",
    "IMP_B_v2",
]
WAFERS = [f"LOT{random.randint(1000, 9999)}-W{str(i).zfill(2)}" for i in range(1, 26)]
STAGES = ["LOAD", "PUMP_DOWN", "PROCESS", "PURGE", "VENT", "UNLOAD", "IDLE"]

ALARM_CODES = {
    "ERROR": [
        "E001_TEMP_HIGH",
        "E002_PRESSURE_FAULT",
        "E003_GAS_FLOW_LOW",
        "E004_RF_REFLECT_HIGH",
        "E005_VACUUM_LEAK",
        "E006_INTERLOCK_TRIP",
    ],
    "WARNING": [
        "W101_TEMP_DRIFT",
        "W102_FLOW_UNSTABLE",
        "W103_ENDPOINT_DELAY",
        "W104_RECIPE_DEVIATION",
    ],
    "CRITICAL": ["C201_SAFETY_INTLK", "C202_DOOR_OPEN", "C203_FIRE_SUPPRESSION"],
}

# Per-tool parameter ranges reflecting real semiconductor process physics.
# Format: param -> (lo, hi, unit, noise_stddev)
# None tuple means this parameter is not applicable for this tool (never generated).
TOOL_PARAMS: dict[str, dict] = {
    "ETCH-01": {
        "temperature": (180, 250, "°C", 0.8),
        "pressure": (5, 20, "mTorr", 0.3),
        "flow_rate": (50, 150, "sccm", 1.5),
        "rf_power": (200, 600, "W", 3.0),
        "chuck_temp": (15, 25, "°C", 0.1),
        "vacuum_level": (1e-4, 5e-4, "Torr", 5e-6),
    },
    "ETCH-02": {
        "temperature": (200, 280, "°C", 0.8),
        "pressure": (3, 15, "mTorr", 0.3),
        "flow_rate": (60, 160, "sccm", 1.5),
        "rf_power": (250, 650, "W", 3.0),
        "chuck_temp": (10, 20, "°C", 0.1),
        "vacuum_level": (5e-5, 3e-4, "Torr", 4e-6),
    },
    "CVD-03": {
        "temperature": (550, 750, "°C", 1.5),
        "pressure": (100, 600, "mTorr", 5.0),
        "flow_rate": (200, 500, "sccm", 4.0),
        "rf_power": (0, 50, "W", 0.5),
        "chuck_temp": (550, 750, "°C", 1.5),
        "vacuum_level": (1e-3, 5e-3, "Torr", 1e-4),
    },
    "PVD-04": {
        "temperature": (50, 200, "°C", 0.5),
        "pressure": (1, 5, "mTorr", 0.1),
        "flow_rate": (10, 40, "sccm", 0.5),
        "rf_power": (100, 400, "W", 2.0),
        "chuck_temp": (20, 60, "°C", 0.3),
        "vacuum_level": (1e-7, 9e-7, "Torr", 5e-9),
    },
    "CMP-05": {
        "temperature": (20, 45, "°C", 0.3),
        "pressure": None,  # N/A — mechanical process
        "flow_rate": (100, 300, "mL/min", 3.0),
        "rf_power": None,  # N/A
        "chuck_temp": (18, 30, "°C", 0.2),
        "vacuum_level": None,  # N/A
    },
    "LITHO-06": {
        "temperature": (20, 23, "°C", 0.05),
        "pressure": (700, 760, "mTorr", 1.0),
        "flow_rate": (10, 30, "sccm", 0.2),
        "rf_power": None,  # N/A
        "chuck_temp": (20, 23, "°C", 0.05),
        "vacuum_level": (1e-2, 5e-2, "Torr", 5e-4),
    },
    "IMP-07": {
        "temperature": (100, 200, "°C", 0.8),
        "pressure": (1e-3, 5e-3, "mTorr", 5e-5),
        "flow_rate": (5, 30, "sccm", 0.4),
        "rf_power": (400, 900, "W", 4.0),
        "chuck_temp": (10, 25, "°C", 0.2),
        "vacuum_level": (1e-7, 5e-7, "Torr", 2e-9),
    },
    "ANNEAL-08": {
        "temperature": (800, 1100, "°C", 2.0),
        "pressure": (700, 760, "mTorr", 1.0),
        "flow_rate": (500, 2000, "sccm", 10.0),
        "rf_power": None,  # N/A — thermal only
        "chuck_temp": (800, 1100, "°C", 2.0),
        "vacuum_level": None,  # N/A — atmospheric
    },
}

EVENTS = [
    "Recipe started",
    "Recipe completed",
    "Wafer loaded",
    "Wafer unloaded",
    "Endpoint detected",
    "Process step completed",
    "Pump engaged",
    "Chamber vented",
    "RF power applied",
    "Gas flow stabilized",
    "Temperature stabilized",
    "Maintenance PM completed",
    "System initialized",
]


def _ts(base: datetime.datetime, delta_s: int) -> datetime.datetime:
    return base + datetime.timedelta(seconds=delta_s)


def _random_entry(base: datetime.datetime, offset: int) -> dict[str, object]:
    t = _ts(base, offset)
    tool = random.choice(TOOLS)
    sev_weights = [
        ("INFO", 0.60),
        ("WARNING", 0.20),
        ("ERROR", 0.15),
        ("CRITICAL", 0.05),
    ]
    severity = random.choices([s for s, _ in sev_weights], [w for _, w in sev_weights])[
        0
    ]

    entry: dict[str, object] = {
        "timestamp": t.isoformat(),
        "tool_id": tool,
        "severity": severity,
        "recipe_id": random.choice(RECIPES),
        "wafer_id": random.choice(WAFERS),
        "process_stage": random.choice(STAGES),
    }

    if severity in ("ERROR", "CRITICAL", "WARNING"):
        entry["alarm_code"] = random.choice(ALARM_CODES.get(severity, ["UNKNOWN"]))
        entry["event_name"] = f"Alarm triggered: {entry['alarm_code']}"
    else:
        entry["event_name"] = random.choice(EVENTS)

    # Add sensor reading ~60 % of the time
    if random.random() > 0.4:
        tool_p = TOOL_PARAMS.get(tool, {})
        # Filter out N/A params (value is None) for this tool
        valid_params = [(k, v) for k, v in tool_p.items() if v is not None]
        if valid_params:
            pname, (lo, hi, unit, noise) = random.choice(valid_params)
            val = round(random.uniform(lo, hi) + random.gauss(0, noise), 4)
            entry["parameter_name"] = pname
            entry["parameter_value"] = val
            entry["unit"] = unit

    return entry


def generate_all(n: int) -> list[dict]:
    """Generate *n* log entries starting from a fixed base timestamp."""
    base = datetime.datetime(2024, 3, 1, 8, 0, 0)
    return [_random_entry(base, i * random.randint(10, 120)) for i in range(n)]


# ---------------------------------------------------------------------------
# Format writers (unchanged)
# ---------------------------------------------------------------------------


def write_json(entries: list[dict], path: str):
    with open(path, "w") as f:
        json.dump(entries, f, indent=2, default=str)


def write_csv(entries: list[dict], path: str):
    import csv

    if not entries:
        return
    keys = list(entries[0].keys())
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(entries)


def write_xml(entries: list[dict], path: str):
    root = ET.Element("ToolLogs")
    for e in entries:
        entry_el = ET.SubElement(root, "LogEntry")
        for k, v in e.items():
            child = ET.SubElement(entry_el, k)
            child.text = str(v) if v is not None else ""
    xml_str = minidom.parseString(ET.tostring(root)).toprettyxml(indent="  ")
    with open(path, "w") as f:
        f.write(xml_str)


def write_syslog(entries: list[dict], path: str):
    SYSLOG_SEV = {"DEBUG": 7, "INFO": 6, "WARNING": 4, "ERROR": 3, "CRITICAL": 2}
    lines = []
    for e in entries:
        pri = 16 * 8 + SYSLOG_SEV.get(e.get("severity", "INFO"), 6)
        ts = e.get("timestamp", "")[:19].replace("T", " ")
        host = e.get("tool_id", "UNKNOWN").replace(" ", "_")
        proc = "tool_controller"
        msg_parts = [e.get("event_name", "")]
        if e.get("alarm_code"):
            msg_parts.append(f"alarm_code={e['alarm_code']}")
        if e.get("parameter_name"):
            msg_parts.append(
                f"{e['parameter_name']}={e['parameter_value']}{e.get('unit', '')}"
            )
        if e.get("wafer_id"):
            msg_parts.append(f"wafer={e['wafer_id']}")
        msg = " ".join(filter(None, msg_parts))
        lines.append(f"<{pri}>{ts} {host} {proc}[1234]: {msg}")
    with open(path, "w") as f:
        f.write("\n".join(lines))


def write_text(entries: list[dict], path: str):
    SEV_TAG = {
        "DEBUG": "DBG",
        "INFO": "INF",
        "WARNING": "WRN",
        "ERROR": "ERR",
        "CRITICAL": "CRT",
    }
    lines = [
        "# Semiconductor Tool Event Log — Maintenance & Process Record",
        "# Generated for demo purposes\n",
    ]
    for e in entries:
        ts = str(e.get("timestamp", ""))[:19]
        tool = e.get("tool_id", "UNKNOWN")
        sev = SEV_TAG.get(e.get("severity", "INFO"), "INF")
        evt = e.get("event_name", "")
        line = f"{ts} [{tool}] {sev}: {evt}"
        if e.get("alarm_code"):
            line += f" | alarm_code={e['alarm_code']}"
        if e.get("recipe_id"):
            line += f" | recipe={e['recipe_id']}"
        if e.get("wafer_id"):
            line += f" | wafer={e['wafer_id']}"
        if e.get("parameter_name"):
            line += (
                f" | {e['parameter_name']}={e['parameter_value']}{e.get('unit', '')}"
            )
        lines.append(line)
    with open(path, "w") as f:
        f.write("\n".join(lines))


def write_key_value(entries: list[dict], path: str):
    lines = []
    for e in entries:
        parts = [f"{k}={v}" for k, v in e.items() if v is not None]
        lines.append(" || ".join(parts))
    with open(path, "w") as f:
        f.write("\n".join(lines))


def write_binary(entries: list[dict], path: str):
    import struct

    with open(path, "wb") as f:
        # Magic bytes for proprietary log
        f.write(b"\x89BNL\r\n\x1a\n\x00\x00")
        for e in entries:
            # Simple length-prefixed, null-delimited payload
            rec = b"\x00".join(
                f"{k}={v}".encode("utf-8") for k, v in e.items() if v is not None
            )
            f.write(struct.pack("<I", len(rec)) + rec)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def generate_sample_files(output_dir: str = "synthetic/samples"):
    # ── Row count: random between 1 000 and 5 000 ───────────────────────────
    n_rows = random.randint(1_000, 5_000)
    print(f"  rows={n_rows}")

    os.makedirs(output_dir, exist_ok=True)

    files = {}
    for fmt, writer, ext in [
        ("json", write_json, "json"),
        ("csv", write_csv, "csv"),
        ("xml", write_xml, "xml"),
        ("syslog", write_syslog, "log"),
        ("text", write_text, "txt"),
        ("kv", write_key_value, "kv"),
        ("binary", write_binary, "bin"),
    ]:
        entries = generate_all(n_rows)
        path = os.path.join(output_dir, f"tool_log_{fmt}.{ext}")
        writer(entries, path)
        files[fmt] = path
        print(f"  ✓  {path}  ({n_rows} entries)")

    return files


if __name__ == "__main__":
    print("Generating synthetic semiconductor tool logs...")
    files = generate_sample_files()
    print(f"\nGenerated {len(files)} sample files in synthetic/samples/")
