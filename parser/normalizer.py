"""
Normalizer: maps heterogeneous raw field names/values to the standard LogEntry schema.
"""

import re
from typing import Any
from dateutil import parser as dateparser

# ---------------------------------------------------------------------------
# Field-name alias maps
# ---------------------------------------------------------------------------

TIMESTAMP_ALIASES = {
    "timestamp", "ts", "time", "datetime", "date_time", "log_time",
    "event_time", "occurred_at", "recorded_at", "created_at",
}

TOOL_ID_ALIASES = {
    "tool_id", "toolid", "tool", "machine_id", "machineid", "machine",
    "equipment_id", "equipid", "device_id", "host", "hostname", "source",
    "system", "unit_id",
}

SEVERITY_ALIASES = {
    "severity", "level", "log_level", "loglevel", "priority",
    "importance", "sev", "type", "msg_type",
}

EVENT_NAME_ALIASES = {
    "event_name", "event", "event_type", "eventtype", "action",
    "operation", "step", "process_step", "description", "message",
    "msg", "log_message", "text", "detail",
}

ALARM_CODE_ALIASES = {
    "alarm_code", "alarmcode", "alarm_id", "alarm", "error_code",
    "errorcode", "fault_code", "faultcode", "code",
}

RECIPE_ID_ALIASES = {
    "recipe_id", "recipe", "recipeid", "process_recipe", "job",
}

WAFER_ID_ALIASES = {
    "wafer_id", "waferid", "wafer", "lot_id", "lotid", "lot",
    "substrate_id", "substrateid",
}

PROCESS_STAGE_ALIASES = {
    "process_stage", "stage", "step", "phase", "operation_phase",
}

PARAM_NAME_ALIASES = {
    "parameter_name", "param_name", "param", "parameter", "sensor",
    "sensor_name", "metric", "key",
}

PARAM_VALUE_ALIASES = {
    "parameter_value", "param_value", "value", "reading",
    "sensor_value", "measurement", "val",
}

UNIT_ALIASES = {
    "unit", "units", "uom", "measure",
}

# ---------------------------------------------------------------------------
# Severity normalisation
# ---------------------------------------------------------------------------

SEVERITY_MAP = {
    "debug":    "DEBUG",
    "verbose":  "DEBUG",
    "trace":    "DEBUG",
    "info":     "INFO",
    "inform":   "INFO",
    "information": "INFO",
    "notice":   "INFO",
    "warn":     "WARNING",
    "warning":  "WARNING",
    "caution":  "WARNING",
    "error":    "ERROR",
    "err":      "ERROR",
    "failure":  "ERROR",
    "fail":     "ERROR",
    "fault":    "ERROR",
    "fatal":    "CRITICAL",
    "severe":   "CRITICAL",
    "critical": "CRITICAL",
    "crit":     "CRITICAL",
    "alert":    "CRITICAL",
    "emergency":"CRITICAL",
    "emerg":    "CRITICAL",
}


# ---------------------------------------------------------------------------
# Parameter-name normalisation
# ---------------------------------------------------------------------------

PARAM_ALIAS_MAP = {
    r"temp.*":          "temperature",
    r"pressure.*":      "pressure",
    r"flow.*":          "flow_rate",
    r"power.*":         "power",
    r"voltage.*":       "voltage",
    r"current.*":       "current",
    r"speed.*":         "speed",
    r"rpm.*":           "rotation_speed",
    r"humidity.*":      "humidity",
    r"vac.*":           "vacuum_level",
    r"rf.*":            "rf_power",
    r"gas.*":           "gas_flow",
    r"chuck.*temp.*":   "chuck_temperature",
    r"process.*time.*": "process_time",
}

# ---------------------------------------------------------------------------
# Log-type classification
# ---------------------------------------------------------------------------

LOG_TYPE_PATTERNS = {
    "alarm":        r"alarm|fault|error|fail|critical|emergency",
    "sensor_reading": r"sensor|reading|measur|temperat|pressure|flow|voltage|current",
    "process_step": r"recipe|step|stage|phase|etch|deposit|clean|anneal|ramp",
    "maintenance":  r"mainten|calibrat|clean|replace|inspect|pm\b",
    "info":         r"info|start|stop|complete|finish|init|boot|connect",
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def _match_alias(key: str, alias_set: set) -> bool:
    return key.lower().strip() in alias_set


def _normalise_severity(raw: str) -> str:
    return SEVERITY_MAP.get(raw.lower().strip(), "INFO")


def _normalise_param_name(name: str) -> str:
    name_lower = name.lower().strip()
    for pattern, canonical in PARAM_ALIAS_MAP.items():
        if re.match(pattern, name_lower):
            return canonical
    return name_lower


def _classify_log_type(text: str) -> str:
    text_lower = text.lower()
    for log_type, pattern in LOG_TYPE_PATTERNS.items():
        if re.search(pattern, text_lower):
            return log_type
    return "info"


def _parse_timestamp(raw: Any) -> str | None:
    if not raw:
        return None
    try:
        return dateparser.parse(str(raw)).isoformat()
    except Exception:
        return str(raw)


def _safe_float(val: Any) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def normalise_record(raw: dict, source_format: str, filename: str) -> dict:
    """
    Map a raw parsed record (arbitrary key-value dict) to the standard schema dict.
    Returns a dict ready to pass into LogEntry(**...).
    """
    out: dict[str, Any] = {
        "source_format": source_format,
        "source_filename": filename,
    }

    # Collect any raw_message early so log_type inference works
    raw_msg_candidates = []

    for k, v in raw.items():
        key = k.lower().strip()

        if _match_alias(key, TIMESTAMP_ALIASES):
            out["timestamp"] = _parse_timestamp(v)

        elif _match_alias(key, TOOL_ID_ALIASES):
            out.setdefault("tool_id", str(v))

        elif _match_alias(key, SEVERITY_ALIASES):
            out["severity"] = _normalise_severity(str(v))

        elif _match_alias(key, EVENT_NAME_ALIASES):
            msg = str(v)
            out.setdefault("event_name", msg)
            raw_msg_candidates.append(msg)

        elif _match_alias(key, ALARM_CODE_ALIASES):
            out.setdefault("alarm_code", str(v))

        elif _match_alias(key, RECIPE_ID_ALIASES):
            out.setdefault("recipe_id", str(v))

        elif _match_alias(key, WAFER_ID_ALIASES):
            out.setdefault("wafer_id", str(v))

        elif _match_alias(key, PROCESS_STAGE_ALIASES):
            out.setdefault("process_stage", str(v))

        elif _match_alias(key, PARAM_NAME_ALIASES):
            out.setdefault("parameter_name", _normalise_param_name(str(v)))

        elif _match_alias(key, PARAM_VALUE_ALIASES):
            out.setdefault("parameter_value", _safe_float(v))

        elif _match_alias(key, UNIT_ALIASES):
            out.setdefault("unit", str(v))

        else:
            # Fallback: treat unknown string fields as part of raw message
            if isinstance(v, str) and v.strip():
                raw_msg_candidates.append(f"{k}={v}")

    # Build raw_message
    if raw_msg_candidates:
        out.setdefault("raw_message", " | ".join(raw_msg_candidates))
    else:
        out["raw_message"] = str(raw)

    # Defaults
    out.setdefault("severity", "INFO")
    out.setdefault("tool_id", "UNKNOWN")
    out.setdefault("timestamp", None)

    # Classify log_type from combined text
    combined = " ".join([
        out.get("event_name", ""),
        out.get("alarm_code", ""),
        out.get("raw_message", ""),
    ])
    out.setdefault("log_type", _classify_log_type(combined))

    # Normalised message = clean human version
    parts = []
    if out.get("tool_id"):
        parts.append(f"[{out['tool_id']}]")
    if out.get("severity"):
        parts.append(f"{out['severity']}:")
    if out.get("event_name"):
        parts.append(out["event_name"])
    if out.get("parameter_name") and out.get("parameter_value") is not None:
        unit = out.get("unit", "")
        parts.append(f"| {out['parameter_name']}={out['parameter_value']}{unit}")
    out["normalized_message"] = " ".join(parts) if parts else out.get("raw_message", "")

    return out
