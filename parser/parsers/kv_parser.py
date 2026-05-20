import re
from typing import Generator

# Regex for key=value or key:value
KV_PATTERN = re.compile(r"([\w\.\-]+)\s*[=:]\s*([^\s\|]+)")


def parse(content: str) -> Generator[dict, None, None]:
    for line in content.splitlines():
        if not line.strip() or line.startswith(("#", ";", "[")):
            continue
        matches = dict(KV_PATTERN.findall(line))
        if matches:
            yield matches
        else:
            yield {"raw_message": line}
