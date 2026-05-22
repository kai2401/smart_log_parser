"""
Detect log format from file extension + content sniffing.

Smart Hybrid: returns deterministic format identifiers only.
Falls back to 'kv' or 'text' instead of 'llm'.
"""

import re


def detect_format(filename: str, content_bytes: bytes) -> str:
    """
    Returns one of: 'json' | 'csv' | 'xml' | 'syslog' | 'kv' | 'text' | 'llm'

    'llm' is only returned for true binary formats; the parser pipeline
    will catch this and further attempt KV or text parsing.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    # Check for known binary extensions
    if ext in ("bin", "parquet", "dat"):
        return "llm"

    # Decode what we can for basic sniff
    content = content_bytes[:4096].decode("utf-8", errors="ignore")

    if ext == "json":
        return "json"
    if ext in ("csv", "tsv"):
        return "csv"
    if ext == "xml":
        return "xml"
    if ext in ("log", "syslog"):
        # Could still be plain text — peek at content
        if _looks_like_syslog(content):
            return "syslog"
        # Check for structured text logs before KV
        if _looks_like_text_log(content):
            return "text"
        # Try KV detection before falling back
        if _looks_like_kv(content):
            return "kv"
        return "text"

    # Extension-less or .txt — sniff content
    stripped = content.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return "json"
    if stripped.startswith("<") and "xml" in stripped[:100].lower():
        return "xml"
    if _looks_like_syslog(stripped):
        return "syslog"
    if _looks_like_csv(stripped):
        return "csv"
    # Check for text-log patterns BEFORE KV (text logs often contain key=value in messages)
    if _looks_like_text_log(stripped):
        return "text"
    if _looks_like_kv(stripped):
        return "kv"

    return "text"


def _looks_like_syslog(content: str) -> bool:
    """Matches RFC 3164 / RFC 5424 / ISO syslog patterns."""
    # RFC 3164: "<PRI>Mon DD HH:MM:SS hostname ..."
    syslog_re = re.compile(
        r"^(?:<\d+>)?\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2}",
        re.MULTILINE,
    )
    # ISO with T separator: "2024-01-15T08:30:00 hostname process[pid]:"
    iso_syslog_t_re = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*\w+\[\d+\]:",
        re.MULTILINE,
    )
    # ISO with space separator and optional PRI: "<132>2024-03-01 08:00:00 HOST process[pid]:"
    iso_syslog_space_re = re.compile(
        r"^(?:<\d+>)?\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+\S+\s+\S+\[\d+\]:",
        re.MULTILINE,
    )
    sample = content[:2000]
    return bool(
        syslog_re.search(sample)
        or iso_syslog_t_re.search(sample)
        or iso_syslog_space_re.search(sample)
    )


def _looks_like_csv(content: str) -> bool:
    lines = [line for line in content.splitlines() if line.strip()][:5]
    if not lines:
        return False
    # Check that most lines have the same number of commas
    comma_counts = [line.count(",") for line in lines]
    return max(comma_counts) > 0 and len(set(comma_counts)) <= 2


def _looks_like_kv(content: str) -> bool:
    """Detect key=value style logs (e.g., 'tool_id=ETX01 pressure=5.2')."""
    sample = content[:1000]
    kv_hits = len(re.findall(r"[\w.\-]+\s*=\s*\S+", sample))
    return kv_hits >= 3


def _looks_like_text_log(content: str) -> bool:
    """Detect structured text logs: 'TIMESTAMP [TOOL_ID] SEV: message | k=v'."""
    # Pattern: ISO timestamp followed by bracketed identifier
    text_re = re.compile(
        r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\s+\[", re.MULTILINE
    )
    lines = [l for l in content[:2000].splitlines() if l.strip() and not l.startswith("#")]
    if not lines:
        return False
    matches = sum(1 for l in lines[:10] if text_re.match(l))
    return matches >= 2
