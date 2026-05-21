import re
from typing import Generator

# Regex for key=value where value runs until next delimiter (||, newline, or end)
KV_PAIR = re.compile(r"([\w.\-]+)\s*=\s*(.+?)(?:\s*\|\||\s*$)")
# Simpler fallback for space-delimited KV: key=value_no_spaces
KV_SIMPLE = re.compile(r"([\w.\-]+)\s*=\s*([^\s|]+)")


def parse(content: str) -> Generator[dict, None, None]:
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";", "[")):
            continue

        # Try pipe-delimited format first: key=value || key=value || ...
        if "||" in line:
            segments = [s.strip() for s in line.split("||")]
            record = {}
            for seg in segments:
                m = re.match(r"([\w.\-]+)\s*=\s*(.+)", seg)
                if m:
                    record[m.group(1)] = m.group(2).strip()
            if record:
                # Ensure raw_message is set
                record.setdefault("raw_message", record.get("event_name", line))
                yield record
                continue

        # Fallback: simple space-delimited key=value
        matches = dict(KV_SIMPLE.findall(line))
        if matches:
            matches.setdefault("raw_message", matches.get("event_name", line))
            yield matches
        else:
            yield {"raw_message": line}
