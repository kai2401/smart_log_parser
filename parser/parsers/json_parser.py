import json
from typing import Generator


def parse(content: str) -> Generator[dict, None, None]:
    """Yield raw record dicts from JSON content (array or newline-delimited)."""
    content = content.strip()

    # Try array first
    if content.startswith("["):
        try:
            records = json.loads(content)
            if isinstance(records, list):
                for r in records:
                    if isinstance(r, dict):
                        yield r
                return
        except json.JSONDecodeError:
            pass

    # Try single object
    if content.startswith("{") and not content.startswith("["):
        lines = content.splitlines()
        # Could be newline-delimited JSON (ndjson)
        for line in lines:
            line = line.strip().rstrip(",")
            if line.startswith("{"):
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
            elif line == "[" or line == "]":
                continue
