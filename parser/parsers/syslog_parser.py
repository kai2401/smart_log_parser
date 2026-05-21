import re
from typing import Generator

# RFC 3164: "Jan  1 00:00:00 hostname process[pid]: message"
RFC3164 = re.compile(
    r"(?:<(?P<pri>\d+)>)?"
    r"(?P<month>\w{3})\s+(?P<day>\d+)\s+(?P<time>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+"
    r"(?P<process>[^\[:]+)(?:\[(?P<pid>\d+)\])?:\s*"
    r"(?P<message>.*)"
)

# ISO syslog: "<132>2024-01-15 08:30:00 hostname process[pid]: message"
ISO_SYSLOG = re.compile(
    r"(?:<(?P<pri>\d+)>)?"
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)?)\s+"
    r"(?P<host>\S+)\s+"
    r"(?P<process>[^\[:]+)(?:\[(?P<pid>\d+)\])?:\s*"
    r"(?P<message>.*)"
)

SEVERITY_FROM_PRI = {
    0: "CRITICAL",
    1: "CRITICAL",
    2: "CRITICAL",
    3: "ERROR",
    4: "WARNING",
    5: "INFO",
    6: "INFO",
    7: "DEBUG",
}

# Patterns to extract structured fields from the syslog message body
_WAFER_RE = re.compile(r"\bwafer[_\s]*=\s*(\S+)", re.IGNORECASE)
_RECIPE_RE = re.compile(r"\brecipe[_\s]*[=:]\s*(\S+)", re.IGNORECASE)
_ALARM_RE = re.compile(r"\balarm_code[_\s]*=\s*(\S+)", re.IGNORECASE)
# Known single-word parameter names (no underscore required)
_SINGLE_PARAMS = (
    "temperature|pressure|voltage|current|power|humidity|"
    "rpm|torque|thickness|dose|resistance|capacitance"
)
# Parameter: name=value with optional unit (e.g., "temperature=180.5°C", "rf_power=350W")
_PARAM_RE = re.compile(
    r"\b(?:([a-z][a-z0-9]*(?:_[a-z][a-z0-9]*)+)|(" + _SINGLE_PARAMS + r"))\s*=\s*"
    r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
    r"([°%a-zA-Z/]+)?",
    re.IGNORECASE,
)
# Known parameter names for disambiguation
_KNOWN_PARAMS = {
    "temperature", "pressure", "flow_rate", "rf_power", "chuck_temp",
    "vacuum_level", "voltage", "current", "power", "dose_energy",
    "precursor_flow", "rotation_speed", "humidity", "rpm", "torque",
    "thickness", "dose", "resistance", "capacitance",
}


def _pri_to_severity(pri_str: str | None) -> str:
    if pri_str is None:
        return "INFO"
    try:
        facility_severity = int(pri_str) % 8
        return SEVERITY_FROM_PRI.get(facility_severity, "INFO")
    except ValueError:
        return "INFO"


def _extract_message_fields(message: str) -> dict:
    """
    Extract structured fields (wafer, recipe, alarm, parameters)
    from the syslog message body.
    """
    fields: dict = {}

    # Wafer ID
    m = _WAFER_RE.search(message)
    if m:
        fields["wafer_id"] = m.group(1).strip()

    # Recipe ID
    m = _RECIPE_RE.search(message)
    if m:
        fields["recipe_id"] = m.group(1).strip()

    # Alarm code
    m = _ALARM_RE.search(message)
    if m:
        fields["alarm_code"] = m.group(1).strip()

    # Parameter extraction: look for param_name=value patterns
    for pm in _PARAM_RE.finditer(message):
        param_name = pm.group(1) or pm.group(2)  # underscore name or single-word name
        if not param_name:
            continue
        # Only extract if it looks like a real sensor parameter (not alarm_code, wafer, etc.)
        if param_name in _KNOWN_PARAMS or "_" in param_name:
            if param_name not in ("alarm_code", "wafer_id", "recipe_id", "tool_id"):
                fields.setdefault("parameter_name", param_name)
                fields.setdefault("parameter_value", pm.group(3))
                if pm.group(4):
                    fields.setdefault("unit", pm.group(4).strip())
                break

    # Clean event name: strip out the key=value metadata from the message
    # to get just the human-readable event description
    event_text = message
    # Remove key=value pairs (including value+unit like "180.5°C")
    event_text = re.sub(
        r"\b(?:wafer|alarm_code|recipe)\s*=\s*\S+", "", event_text
    )
    event_text = re.sub(
        r"\b[a-z][a-z0-9_]*(?:_[a-z]+)+\s*=\s*-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?[°%a-zA-Z/]*",
        "", event_text, flags=re.IGNORECASE
    )
    event_text = event_text.strip(" |")
    if event_text:
        fields["event_name"] = event_text

    return fields


def parse(content: str) -> Generator[dict, None, None]:
    """Yield raw record dicts from syslog content."""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue

        m = ISO_SYSLOG.match(line)
        if m:
            msg = m.group("message").strip()
            record = {
                "timestamp": m.group("timestamp"),
                "tool_id": m.group("host"),
                "process": m.group("process").strip(),
                "message": msg,
                "severity": _pri_to_severity(m.group("pri")),
                "raw_message": msg,
            }
            # Extract structured fields from message body
            record.update(_extract_message_fields(msg))
            yield record
            continue

        m = RFC3164.match(line)
        if m:
            ts = f"{m.group('month')} {m.group('day')} {m.group('time')}"
            msg = m.group("message").strip()
            record = {
                "timestamp": ts,
                "tool_id": m.group("host"),
                "process": m.group("process").strip(),
                "message": msg,
                "severity": _pri_to_severity(m.group("pri")),
                "raw_message": msg,
            }
            # Extract structured fields from message body
            record.update(_extract_message_fields(msg))
            yield record
            continue

        # Fallback: treat whole line as message
        yield {"message": line, "severity": "INFO"}
