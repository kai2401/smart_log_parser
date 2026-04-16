import re
from typing import Generator

# Common timestamp patterns
TS_PATTERNS = [
    re.compile(r"(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"),
    re.compile(r"(?P<timestamp>\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})"),
    re.compile(r"(?P<timestamp>\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})"),
]

SEVERITY_RE = re.compile(
    r"\b(?P<severity>DEBUG|INFO|NOTICE|WARNING|WARN|ERROR|CRITICAL|CRIT|ALERT|FAULT|FAIL)\b",
    re.IGNORECASE,
)

TOOL_ID_RE = re.compile(
    r"^(?P<tool_id>[A-Z]{2,6}[-_]?\d{2,6})\b|"
    r"\[(?P<tool_id2>[A-Z]{2,6}[-_]?\d{2,6})\]|"
    r"(?:tool|machine|equip|host|device)[_\s]*[=:]\s*(?P<tool_id3>[A-Z0-9_\-]+)",
    re.IGNORECASE | re.MULTILINE,
)

PARAM_RE = re.compile(
    r"(?P<param_name>[A-Z][A-Za-z]*(?:Speed|Pressure|Temperature|Flow|Voltage|Current)?)\s*[=:]\s*(?P<param_value>-?\d+(?:\.\d+)?)\s*(?P<unit>(?:Torr|RPM|C|[°%a-zA-Z/]+))?",
)

WAFER_RE = re.compile(
    r"(?:wafer|lot|substrate)[_\s]*[=:#]?\s*(?P<wafer_id>[A-Z0-9_\-]+)",
    re.IGNORECASE,
)

RECIPE_RE = re.compile(
    r"(?:recipe|process)[_\s]*[=:#]?\s*(?P<recipe_id>[A-Za-z0-9_\-]+)",
    re.IGNORECASE,
)


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
            record["severity"] = m.group("severity").upper()

        # Tool ID (try start of line first, then bracketed, then key=value)
        m = TOOL_ID_RE.search(line)
        if m:
            tool_id_val = m.group("tool_id") or m.group("tool_id2") or m.group("tool_id3") or ""
            if tool_id_val:
                record["tool_id"] = tool_id_val.strip()

        # Wafer / lot
        m = WAFER_RE.search(line)
        if m:
            record["wafer_id"] = m.group("wafer_id").strip()

        # Recipe
        m = RECIPE_RE.search(line)
        if m:
            record["recipe_id"] = m.group("recipe_id").strip()

        # Parameter extraction: look for "Name: value Unit" patterns
        params = PARAM_RE.findall(line)
        if params:
            # Use the first valid match (skip timestamp-like matches)
            for pname, pval, punit in params:
                if len(pname) > 1 and not re.match(r"^\d{2}$", pname):  # Skip two-digit numbers
                    record.setdefault("parameter_name", pname)
                    record.setdefault("parameter_value", pval)
                    if punit and punit.strip():
                        record.setdefault("unit", punit.strip())
                    break

        # Event name: everything after timestamp + severity + tool_id (heuristic)
        event_candidate = re.sub(
            r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\s]*|\[[A-Z0-9_\-]+\]|"
            r"\b(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\b",
            "",
            line,
            flags=re.IGNORECASE,
        ).strip(" :|")
        if event_candidate:
            record.setdefault("event_name", event_candidate[:200])

        yield record
