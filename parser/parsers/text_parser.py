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
    r"\[(?P<tool_id>[A-Z]{2,6}[-_]?\d{2,6})\]|"
    r"(?:tool|machine|equip|host|device)[_\s]*[=:]\s*(?P<tool_id2>[A-Z0-9_\-]+)",
    re.IGNORECASE,
)

ALARM_RE = re.compile(
    r"(?:alarm|fault|error|code)[_\s]*[=:#]?\s*(?P<alarm_code>[A-Z0-9_\-]{3,16})",
    re.IGNORECASE,
)

PARAM_RE = re.compile(
    r"(?P<param_name>[A-Za-z_][A-Za-z0-9_]*)\s*[=:]\s*(?P<param_value>-?\d+(?:\.\d+)?)\s*(?P<unit>[°%a-zA-Z/]+)?",
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

        # Tool ID
        m = TOOL_ID_RE.search(line)
        if m:
            record["tool_id"] = (m.group("tool_id") or m.group("tool_id2") or "").strip()

        # Alarm code
        m = ALARM_RE.search(line)
        if m:
            record["alarm_code"] = m.group("alarm_code").strip()

        # Wafer / lot
        m = WAFER_RE.search(line)
        if m:
            record["wafer_id"] = m.group("wafer_id").strip()

        # Recipe
        m = RECIPE_RE.search(line)
        if m:
            record["recipe_id"] = m.group("recipe_id").strip()

        # Parameter extraction (first numeric k=v pair)
        params = PARAM_RE.findall(line)
        if params:
            # Skip single-char or timestamp-like matches
            for pname, pval, punit in params:
                if len(pname) > 2 and not re.match(r"^\d", pname):
                    record["parameter_name"] = pname
                    record["parameter_value"] = pval
                    if punit:
                        record["unit"] = punit.strip()
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
