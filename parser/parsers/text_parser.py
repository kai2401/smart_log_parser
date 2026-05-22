import re
from typing import Generator

# Common timestamp patterns
TS_PATTERNS = [
    re.compile(
        r"(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
    ),
    re.compile(r"(?P<timestamp>\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})"),
    re.compile(r"(?P<timestamp>\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})"),
]

SEVERITY_RE = re.compile(
    r"\b(?P<severity>DEBUG|DBG|INFO|INF|NOTICE|WARNING|WARN|WRN|ERROR|ERR|CRITICAL|CRIT|CRT|ALERT|FAULT|FAIL|FATAL)\b",
    re.IGNORECASE,
)

# Severity tag normalisation map
_SEV_MAP = {
    "DBG": "DEBUG",
    "INF": "INFO",
    "WRN": "WARNING",
    "ERR": "ERROR",
    "CRT": "CRITICAL",
    "CRIT": "CRITICAL",
}

TOOL_ID_RE = re.compile(
    r"^(?P<tool_id>[A-Z]{2,6}[-_]?\d{2,6})\b|"
    r"\[(?P<tool_id2>[A-Z]{2,10}[-_]\d{1,6})\]|"
    r"(?:tool|machine|equip|host|device)[_\s]*[=:]\s*(?P<tool_id3>[A-Z0-9_\-]+)",
    re.IGNORECASE | re.MULTILINE,
)

# Wafer/lot: wafer=LOT1234-W01 or wafer LOT1234-W01
WAFER_RE = re.compile(
    r"(?:wafer|lot|substrate)[_\s]*[=:#]?\s*(?P<wafer_id>[A-Z]{2,}[0-9]+[-_][A-Z]?\d+)",
    re.IGNORECASE,
)

# Recipe: recipe=ETH_SiO2_v3 — require at least one underscore to avoid false positives
# like matching "completed" from "Recipe completed"
RECIPE_RE = re.compile(
    r"(?:recipe)[_\s]*[=:#]\s*(?P<recipe_id>[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+)",
    re.IGNORECASE,
)

# Parameter: name=value with optional unit
# Handles underscore-based names like vacuum_level=0.0005Torr, rf_power=350W
# Also handles known single-word names like temperature=180.5°C, pressure=5.0mTorr
_SINGLE_PARAMS = (
    "temperature|pressure|voltage|current|power|humidity|"
    "rpm|torque|thickness|dose|resistance|capacitance"
)
PARAM_RE = re.compile(
    r"\b(?:(?P<param_name>[a-z][a-z0-9]*(?:_[a-z][a-z0-9]*)+)|(?P<param_single>"
    + _SINGLE_PARAMS
    + r"))\s*=\s*"
    r"(?P<param_value>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
    r"(?P<unit>[°%a-zA-Z/]+)?",
    re.IGNORECASE,
)

# Known non-parameter key=value fields to skip
_SKIP_PARAMS = {
    "alarm_code",
    "recipe_id",
    "wafer_id",
    "tool_id",
    "event_name",
    "process_stage",
}


def parse(content: str) -> Generator[dict, None, None]:
    """Parse unstructured plain-text logs line by line."""
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        record: dict = {"raw_message": line}

        # Timestamp
        for ts_re in TS_PATTERNS:
            m = ts_re.search(line)
            if m:
                record["timestamp"] = m.group("timestamp")
                break

        # Severity
        m = SEVERITY_RE.search(line)
        if m:
            raw_sev = m.group("severity").upper()
            record["severity"] = _SEV_MAP.get(raw_sev, raw_sev)

        # Tool ID (try bracketed first like [ETCH-01], then start of line, then key=value)
        m = TOOL_ID_RE.search(line)
        if m:
            tool_id_val = (
                m.group("tool_id") or m.group("tool_id2") or m.group("tool_id3") or ""
            )
            if tool_id_val:
                record["tool_id"] = tool_id_val.strip()

        # Wafer / lot
        m = WAFER_RE.search(line)
        if m:
            record["wafer_id"] = m.group("wafer_id").strip()

        # Recipe (requires underscore in ID to avoid false positives)
        m = RECIPE_RE.search(line)
        if m:
            record["recipe_id"] = m.group("recipe_id").strip()

        # Parameter extraction: look for param_name=valueUnit patterns
        for pm in PARAM_RE.finditer(line):
            pname = pm.group("param_name") or pm.group("param_single")
            if not pname:
                continue
            # Skip non-parameter fields
            if pname.lower() in _SKIP_PARAMS:
                continue
            record.setdefault("parameter_name", pname)
            record.setdefault("parameter_value", pm.group("param_value"))
            if pm.group("unit") and pm.group("unit").strip():
                record.setdefault("unit", pm.group("unit").strip())
            break

        # Event name: extract the human-readable event description
        # Format is typically: "timestamp [TOOL] SEV: Event description | key=value | ..."
        # Strip timestamp, tool bracket, severity tag, and trailing key=value pairs
        event_text = line
        # Remove timestamp
        event_text = re.sub(
            r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\s]*", "", event_text
        )
        # Remove bracketed tool ID
        event_text = re.sub(r"\[[A-Z0-9_\-]+\]", "", event_text)
        # Remove severity tag
        event_text = re.sub(
            r"\b(?:DEBUG|DBG|INFO|INF|WARNING|WARN|WRN|ERROR|ERR|CRITICAL|CRIT|CRT|ALERT|FAULT|FAIL|FATAL)\b",
            "",
            event_text,
            flags=re.IGNORECASE,
        )
        # Split on pipe delimiter and take just the event description (first part)
        parts = event_text.split("|")
        event_name = parts[0].strip(" :")
        if event_name:
            record.setdefault("event_name", event_name[:200])

        yield record
