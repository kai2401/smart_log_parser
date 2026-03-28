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

# ISO syslog: "2024-01-15T08:30:00 hostname process[pid]: message"
ISO_SYSLOG = re.compile(
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)?)\s+"
    r"(?P<host>\S+)\s+"
    r"(?P<process>[^\[:]+)(?:\[(?P<pid>\d+)\])?:\s*"
    r"(?P<message>.*)"
)

SEVERITY_FROM_PRI = {
    0: "CRITICAL", 1: "CRITICAL", 2: "CRITICAL",
    3: "ERROR",    4: "WARNING",
    5: "INFO",     6: "INFO",
    7: "DEBUG",
}


def _pri_to_severity(pri_str: str | None) -> str:
    if pri_str is None:
        return "INFO"
    try:
        facility_severity = int(pri_str) % 8
        return SEVERITY_FROM_PRI.get(facility_severity, "INFO")
    except ValueError:
        return "INFO"


def parse(content: str) -> Generator[dict, None, None]:
    """Yield raw record dicts from syslog content."""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue

        m = ISO_SYSLOG.match(line)
        if m:
            yield {
                "timestamp": m.group("timestamp"),
                "tool_id":   m.group("host"),
                "event_name": m.group("process").strip(),
                "message":   m.group("message"),
                "severity":  "INFO",
            }
            continue

        m = RFC3164.match(line)
        if m:
            ts = f"{m.group('month')} {m.group('day')} {m.group('time')}"
            yield {
                "timestamp": ts,
                "tool_id":   m.group("host"),
                "event_name": m.group("process").strip(),
                "message":   m.group("message"),
                "severity":  _pri_to_severity(m.group("pri")),
            }
            continue

        # Fallback: treat whole line as message
        yield {"message": line, "severity": "INFO"}
