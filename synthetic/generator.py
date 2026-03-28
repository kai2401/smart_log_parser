"""
Synthetic semiconductor tool log generator.
Produces realistic logs in JSON, CSV, XML, Syslog, and plain text formats.
"""

import json
import random
import datetime
import os
import xml.etree.ElementTree as ET
from xml.dom import minidom

random.seed(42)

TOOLS = ["ETCH-01", "ETCH-02", "CVD-03", "PVD-04", "CMP-05", "LITHO-06", "IMP-07", "ANNEAL-08"]
RECIPES = ["ETH_SiO2_v3", "CVD_TiN_v2", "PVD_Al_v1", "CMP_Cu_v4", "LITHO_DUV_v5", "IMP_B_v2"]
WAFERS  = [f"LOT{random.randint(1000,9999)}-W{str(i).zfill(2)}" for i in range(1, 26)]
STAGES  = ["LOAD", "PUMP_DOWN", "PROCESS", "PURGE", "VENT", "UNLOAD", "IDLE"]

ALARM_CODES = {
    "ERROR":    ["E001_TEMP_HIGH", "E002_PRESSURE_FAULT", "E003_GAS_FLOW_LOW",
                 "E004_RF_REFLECT_HIGH", "E005_VACUUM_LEAK", "E006_INTERLOCK_TRIP"],
    "WARNING":  ["W101_TEMP_DRIFT", "W102_FLOW_UNSTABLE", "W103_ENDPOINT_DELAY",
                 "W104_RECIPE_DEVIATION"],
    "CRITICAL": ["C201_SAFETY_INTLK", "C202_DOOR_OPEN", "C203_FIRE_SUPPRESSION"],
}

PARAMS = {
    "temperature":   (350, 450, "°C",  0.5),
    "pressure":      (5,   15,  "mTorr", 0.2),
    "flow_rate":     (80,  120, "sccm", 1.0),
    "rf_power":      (300, 500, "W",   2.0),
    "chuck_temp":    (20,  25,  "°C",  0.1),
    "vacuum_level":  (1e-6, 5e-6, "Torr", 1e-7),
}

EVENTS = [
    "Recipe started", "Recipe completed", "Wafer loaded", "Wafer unloaded",
    "Endpoint detected", "Process step completed", "Pump engaged",
    "Chamber vented", "RF power applied", "Gas flow stabilized",
    "Temperature stabilized", "Maintenance PM completed", "System initialized",
]


def _ts(base: datetime.datetime, delta_s: int) -> datetime.datetime:
    return base + datetime.timedelta(seconds=delta_s)


def _random_entry(base: datetime.datetime, offset: int) -> dict:
    t = _ts(base, offset)
    tool = random.choice(TOOLS)
    sev_weights = [("INFO", 0.60), ("WARNING", 0.20), ("ERROR", 0.15), ("CRITICAL", 0.05)]
    severity = random.choices([s for s, _ in sev_weights], [w for _, w in sev_weights])[0]

    entry = {
        "timestamp":    t.isoformat(),
        "tool_id":      tool,
        "severity":     severity,
        "recipe_id":    random.choice(RECIPES),
        "wafer_id":     random.choice(WAFERS),
        "process_stage": random.choice(STAGES),
    }

    if severity in ("ERROR", "CRITICAL", "WARNING"):
        entry["alarm_code"] = random.choice(ALARM_CODES.get(severity, ["UNKNOWN"]))
        entry["event_name"] = f"Alarm triggered: {entry['alarm_code']}"
    else:
        entry["event_name"] = random.choice(EVENTS)

    # Add sensor reading ~60% of the time
    if random.random() > 0.4:
        pname, (lo, hi, unit, noise) = random.choice(list(PARAMS.items()))
        val = round(random.uniform(lo, hi) + random.gauss(0, noise), 4)
        entry["parameter_name"]  = pname
        entry["parameter_value"] = val
        entry["unit"]             = unit

    return entry


def generate_all(n: int = 50) -> list[dict]:
    base = datetime.datetime(2024, 3, 1, 8, 0, 0)
    return [_random_entry(base, i * random.randint(10, 120)) for i in range(n)]


# ---------------------------------------------------------------------------
# Format writers
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
            msg_parts.append(f"{e['parameter_name']}={e['parameter_value']}{e.get('unit','')}")
        if e.get("wafer_id"):
            msg_parts.append(f"wafer={e['wafer_id']}")
        msg = " ".join(filter(None, msg_parts))
        lines.append(f"<{pri}>{ts} {host} {proc}[1234]: {msg}")
    with open(path, "w") as f:
        f.write("\n".join(lines))


def write_text(entries: list[dict], path: str):
    SEV_TAG = {"DEBUG": "DBG", "INFO": "INF", "WARNING": "WRN", "ERROR": "ERR", "CRITICAL": "CRT"}
    lines = ["# Semiconductor Tool Event Log — Maintenance & Process Record",
             "# Generated for demo purposes\n"]
    for e in entries:
        ts   = str(e.get("timestamp", ""))[:19]
        tool = e.get("tool_id", "UNKNOWN")
        sev  = SEV_TAG.get(e.get("severity", "INFO"), "INF")
        evt  = e.get("event_name", "")
        parts = [f"{ts} [{tool}] {sev}: {evt}"]
        if e.get("alarm_code"):
            parts[0] += f" | alarm_code={e['alarm_code']}"
        if e.get("recipe_id"):
            parts[0] += f" | recipe={e['recipe_id']}"
        if e.get("wafer_id"):
            parts[0] += f" | wafer={e['wafer_id']}"
        if e.get("parameter_name"):
            parts[0] += f" | {e['parameter_name']}={e['parameter_value']}{e.get('unit','')}"
        lines.append(parts[0])
    with open(path, "w") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def generate_sample_files(output_dir: str = "synthetic/samples", n_each: int = 60):
    os.makedirs(output_dir, exist_ok=True)

    files = {}
    for fmt, writer, ext in [
        ("json",   write_json,   "json"),
        ("csv",    write_csv,    "csv"),
        ("xml",    write_xml,    "xml"),
        ("syslog", write_syslog, "log"),
        ("text",   write_text,   "txt"),
    ]:
        entries = generate_all(n_each)
        path = os.path.join(output_dir, f"tool_log_{fmt}.{ext}")
        writer(entries, path)
        files[fmt] = path
        print(f"  ✓  {path}  ({n_each} entries)")

    return files


if __name__ == "__main__":
    print("Generating synthetic semiconductor tool logs...")
    files = generate_sample_files()
    print(f"\nGenerated {len(files)} sample files in synthetic/samples/")
