"""
Normalizer: maps heterogeneous raw field names/values to the standard LogEntry schema.

Best-effort approach: missing timestamps default to now(), missing tool_id defaults
to the filename stem. No field absence will crash the pipeline.
"""

import re
from datetime import datetime
from typing import Any
from dateutil import parser as dateparser

# Drain3 for template mining (used internally, not stored)
try:
    import os
    from drain3 import TemplateMiner
    from drain3.template_miner_config import TemplateMinerConfig

    _config = TemplateMinerConfig()
    _ini_path = os.path.join(os.path.dirname(__file__), "drain3.ini")
    if os.path.exists(_ini_path):
        _config.load(_ini_path)
    _template_miner = TemplateMiner(config=_config)
except ImportError:
    _template_miner = None

# ---------------------------------------------------------------------------
# Field-name alias maps
# ---------------------------------------------------------------------------

TIMESTAMP_ALIASES = {
    "timestamp",
    "ts",
    "time",
    "datetime",
    "date_time",
    "log_time",
    "event_time",
    "occurred_at",
    "recorded_at",
    "created_at",
}

TOOL_ID_ALIASES = {
    "tool_id",
    "toolid",
    "tool",
    "machine_id",
    "machineid",
    "machine",
    "equipment_id",
    "equipid",
    "device_id",
    "host",
    "hostname",
    "source",
    "system",
    "unit_id",
}

SEVERITY_ALIASES = {
    "severity",
    "level",
    "log_level",
    "loglevel",
    "priority",
    "importance",
    "sev",
    "type",
    "msg_type",
}

EVENT_NAME_ALIASES = {
    "event_name",
    "event",
    "event_type",
    "eventtype",
    "action",
    "operation",
    "step",
    "process_step",
    "description",
    "message",
    "msg",
    "log_message",
    "text",
    "detail",
}

RECIPE_ID_ALIASES = {
    "recipe_id",
    "recipe",
    "recipeid",
    "process_recipe",
    "job",
}

WAFER_ID_ALIASES = {
    "wafer_id",
    "waferid",
    "wafer",
    "lot_id",
    "lotid",
    "lot",
    "substrate_id",
    "substrateid",
}

PROCESS_STAGE_ALIASES = {
    "process_stage",
    "stage",
    "step",
    "phase",
    "operation_phase",
}

PARAM_NAME_ALIASES = {
    "parameter_name",
    "param_name",
    "param",
    "parameter",
    "sensor",
    "sensor_name",
    "metric",
    "key",
    "setpoint_name",
}

PARAM_VALUE_ALIASES = {
    "parameter_value",
    "param_value",
    "value",
    "reading",
    "sensor_value",
    "measurement",
    "val",
    "setpoint_value",
}

UNIT_ALIASES = {
    "unit",
    "units",
    "uom",
    "measure",
}

# ---------------------------------------------------------------------------
# Severity normalisation
# ---------------------------------------------------------------------------

SEVERITY_MAP = {
    "debug": "DEBUG",
    "dbg": "DEBUG",
    "verbose": "DEBUG",
    "trace": "DEBUG",
    "info": "INFO",
    "inf": "INFO",
    "inform": "INFO",
    "information": "INFO",
    "notice": "INFO",
    "warn": "WARNING",
    "wrn": "WARNING",
    "warning": "WARNING",
    "caution": "WARNING",
    "error": "ERROR",
    "err": "ERROR",
    "failure": "ERROR",
    "fail": "ERROR",
    "fault": "ERROR",
    "fatal": "CRITICAL",
    "severe": "CRITICAL",
    "critical": "CRITICAL",
    "crit": "CRITICAL",
    "alert": "CRITICAL",
    "emergency": "CRITICAL",
    "emerg": "CRITICAL",
}


# ---------------------------------------------------------------------------
# Parameter-name normalisation
# ---------------------------------------------------------------------------

PARAM_ALIAS_MAP = {
    r"temp.*": "temperature",
    r"pressure.*": "pressure",
    r"flow.*": "flow_rate",
    r"power.*": "power",
    r"voltage.*": "voltage",
    r"current.*": "current",
    r"speed.*": "speed",
    r"rpm.*": "rotation_speed",
    r"humidity.*": "humidity",
    r"vac.*": "vacuum_level",
    r"rf.*": "rf_power",
    r"gas.*": "gas_flow",
    r"chuck.*temp.*": "chuck_temperature",
    r"process.*time.*": "process_time",
}

# ---------------------------------------------------------------------------
# Log-type classification
# ---------------------------------------------------------------------------

LOG_TYPE_PATTERNS = {
    "alarm": r"alarm|fault|error|fail|critical|emergency",
    "sensor_reading": r"sensor|reading|measur|temperat|pressure|flow|voltage|current",
    "process_step": r"recipe|step|stage|phase|etch|deposit|clean|anneal|ramp",
    "maintenance": r"mainten|calibrat|clean|replace|inspect|pm\b",
    "info": r"info|start|stop|complete|finish|init|boot|connect",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _flatten_dict(d: dict, parent_key: str = "", sep: str = "_") -> dict:
    """Recursively flatten nested dicts into a single-level dict."""
    items: list[tuple[str, Any]] = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten_dict(v, new_key, sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


import json

def normalise_record(
    raw: dict,
    source_format: str,
    filename: str,
    is_recipe: bool = False,
) -> dict:
    """
    Schema-on-Read Normalization with Unstructured Bypass.

    For STRUCTURED formats (json, xml, csv, parquet): performs full alias-based
    field extraction and regex post-processing.

    For UNSTRUCTURED formats (syslog, kv, text, universal, binary): bypasses all
    field mapping and regex guessing. Only raw_message is preserved, with safe
    defaults for required DB columns. This prevents field contamination where
    random strings get misidentified as wafer_ids, recipe_ids, etc.
    """
    flat_raw = _flatten_dict(raw)

    # 1. Base Assignment (Guarantees DB constraints are met)
    out: dict[str, Any] = {
        "source_format": source_format,
        "source_filename": filename,
        "timestamp": flat_raw.get("timestamp") or datetime.now().isoformat(),
        "tool_id": flat_raw.get("tool_id") or "UNKNOWN",
        "severity": flat_raw.get("severity") or "INFO",
        "log_type": "recipe" if is_recipe else flat_raw.get("log_type", "info"),
        "raw_message": flat_raw.get("raw_message") or str(raw),
    }

    metadata: dict[str, Any] = {}

    # 2. Strict Bypass Logic
    STRUCTURED_FORMATS = {"json", "xml", "csv", "parquet"}

    if source_format in STRUCTURED_FORMATS:
        # ── STRUCTURED PATH: full alias-based field extraction ─────────
        raw_msg_candidates = []

        for k, v in flat_raw.items():
            key = k.lower().strip()

            if _match_alias(key, TIMESTAMP_ALIASES):
                out["timestamp"] = _parse_timestamp(v) or out["timestamp"]
            elif _match_alias(key, TOOL_ID_ALIASES):
                out.setdefault("tool_id", str(v))
            elif _match_alias(key, SEVERITY_ALIASES):
                out["severity"] = _normalise_severity(str(v))
            elif _match_alias(key, EVENT_NAME_ALIASES):
                msg = str(v)
                metadata["event_name"] = msg
                raw_msg_candidates.append(msg)
            else:
                if _match_alias(key, RECIPE_ID_ALIASES):
                    metadata["recipe_id"] = str(v)
                elif _match_alias(key, WAFER_ID_ALIASES):
                    metadata["wafer_id"] = str(v)
                elif _match_alias(key, PROCESS_STAGE_ALIASES):
                    metadata["process_stage"] = str(v)
                elif _match_alias(key, PARAM_NAME_ALIASES):
                    metadata["parameter_name"] = _normalise_param_name(str(v))
                elif _match_alias(key, PARAM_VALUE_ALIASES):
                    metadata["parameter_value"] = _safe_float(v)
                elif _match_alias(key, UNIT_ALIASES):
                    metadata["unit"] = str(v)
                else:
                    metadata[k] = v
                    if isinstance(v, str) and v.strip():
                        raw_msg_candidates.append(f"{k}={v}")

        # Build raw_message from structured fields if not already present
        if "raw_message" not in flat_raw:
            if raw_msg_candidates:
                out["raw_message"] = " | ".join(raw_msg_candidates)
            else:
                out["raw_message"] = json.dumps(flat_raw, default=str)

        # ── Default Injection for structured path ─────────────────────
        if not out.get("tool_id") or out.get("tool_id") == "UNKNOWN":
            out["tool_id"] = filename.rsplit(".", 1)[0] if "." in filename else filename
            if not out["tool_id"]:
                out["tool_id"] = "UNKNOWN_TOOL"

        # ── Classify log_type and normalized_message ──────────────────
        combined = " ".join([metadata.get("event_name", ""), out.get("raw_message", "")])
        out.setdefault("log_type", _classify_log_type(combined))

        parts = []
        if out.get("tool_id"):
            parts.append(f"[{out['tool_id']}]")
        if out.get("severity"):
            parts.append(f"{out['severity']}:")
        if metadata.get("event_name"):
            parts.append(metadata["event_name"])
        if metadata.get("parameter_name") and metadata.get("parameter_value") is not None:
            unit = metadata.get("unit", "")
            parts.append(f"| {metadata['parameter_name']}={metadata['parameter_value']}{unit}")
        metadata["normalized_message"] = " ".join(parts) if parts else out.get("raw_message", "")

        # ── Post-processing fallback (structured only) ────────────────
        combined_text = combined.lower()
        if out.get("tool_id") == "UNKNOWN_TOOL":
            tool_match = re.search(r"\b([A-Z]{2,6}[-_]?\d{2,6})\b", metadata.get("event_name", ""))
            if tool_match:
                out["tool_id"] = tool_match.group(1)

        if not metadata.get("parameter_name"):
            param_match = re.search(
                r"(?P<pname>Pressure|Temperature|Flow|Voltage|Current|Speed|RPM|Power|Step|Humidity)\s*[=:]\s*(?P<pval>-?\d+(?:\.\d+)?)\s*(?P<punit>Torr|RPM|C|%|V|A|W)?",
                metadata.get("event_name", ""),
                re.IGNORECASE,
            )
            if param_match:
                metadata["parameter_name"] = _normalise_param_name(param_match.group("pname"))
                metadata["parameter_value"] = _safe_float(param_match.group("pval"))
                if param_match.group("punit"):
                    metadata["unit"] = param_match.group("punit")

        if not metadata.get("wafer_id"):
            wafer_match = re.search(r"(?:wafer|lot|substrate)[_\s]*[=:#]?\s*([A-Z0-9_\-]+)", combined_text, re.IGNORECASE)
            if wafer_match:
                metadata["wafer_id"] = wafer_match.group(1)

        if not metadata.get("recipe_id"):
            recipe_match = re.search(r"(?:recipe|process)[_\s]*[=:#]?\s*([A-Z0-9_\-]+)", combined_text, re.IGNORECASE)
            if recipe_match:
                candidate = recipe_match.group(1)
                if candidate.lower() not in ("start", "stepcomplete", "stop", "complete"):
                    metadata["recipe_id"] = candidate

        if not metadata.get("step_number"):
            step_match = re.search(r"(?:step|stage|phase)\s*(?:no|num|number)?\s*[=:#]?\s*(\d+)", combined_text, re.IGNORECASE)
            if step_match:
                try:
                    metadata["step_number"] = int(step_match.group(1))
                except ValueError:
                    pass

        if is_recipe:
            metadata.setdefault("recipe_id", "UNKNOWN")
            metadata.setdefault("setpoint_name", metadata.get("parameter_name", "UNKNOWN"))
            metadata.setdefault("setpoint_value", metadata.get("parameter_value", 0.0))
            out["log_type"] = "recipe"

    else:
        # ── UNSTRUCTURED PATH (Syslog, KV, Text, Binary, Universal): ──
        # Trust fields the parser explicitly extracted (tool_id, timestamp,
        # severity are already in base assignment). Stash everything else
        # the parser found into metadata — but do NOT run alias-guessing
        # or regex post-processing that causes field contamination.

        # Core fields the parser may have explicitly set (exact key match)
        CORE_KEYS = {"tool_id", "timestamp", "severity", "raw_message",
                     "log_type", "source_format", "source_filename"}

        for k, v in flat_raw.items():
            if k in CORE_KEYS:
                continue  # already handled in base assignment
            # Everything else the parser extracted goes into metadata
            if v is not None and str(v).strip():
                metadata[k] = v

        # Build raw_message from parser's message field if raw_message is missing
        if not flat_raw.get("raw_message"):
            msg = flat_raw.get("message") or flat_raw.get("event_name") or str(raw)
            out["raw_message"] = str(msg)

        # Normalise severity if parser provided it as a raw string
        if flat_raw.get("severity"):
            out["severity"] = _normalise_severity(str(flat_raw["severity"]))

        # Promote severity from message content when parser returned generic INFO
        # (e.g., syslog PRI may say INFO but message contains "ERROR" or "CRITICAL")
        if out["severity"] == "INFO":
            msg_lower = out.get("raw_message", "").lower()
            for sev_word, sev_level in [
                ("critical", "CRITICAL"), ("fatal", "CRITICAL"), ("emergency", "CRITICAL"),
                ("alert", "CRITICAL"), ("error", "ERROR"), ("fault", "ERROR"),
                ("fail", "ERROR"), ("warn", "WARNING"), ("caution", "WARNING"),
            ]:
                if re.search(rf"\b{sev_word}\b", msg_lower):
                    out["severity"] = sev_level
                    break

        # Classify log_type from available text
        event_text = str(metadata.get("event_name", ""))
        msg_text = out.get("raw_message", "")
        combined = f"{event_text} {msg_text}"
        out["log_type"] = _classify_log_type(combined)

        # Default tool_id to filename stem if still unknown
        if not out.get("tool_id") or out.get("tool_id") == "UNKNOWN":
            out["tool_id"] = filename.rsplit(".", 1)[0] if "." in filename else filename
            if not out["tool_id"]:
                out["tool_id"] = "UNKNOWN_TOOL"

    # 3. Execute Drain3 Template Mining (both paths)
    if _template_miner is not None:
        raw_msg = out.get("raw_message", "")
        if raw_msg:
            try:
                result = _template_miner.add_log_message(raw_msg)
                out["drain_cluster_id"] = int(result["cluster_id"])
                metadata["drain_template"] = result["template_mined"]
            except Exception:
                out["drain_cluster_id"] = None

    # Serialize metadata
    out["metadata"] = json.dumps(metadata, default=str)

    return out
