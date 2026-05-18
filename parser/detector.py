"""
Detect log format from file extension + content sniffing.
"""

import re


def detect_format(filename: str, content_bytes: bytes) -> str:
    """
    Returns one of: 'json' | 'csv' | 'xml' | 'syslog' | 'text' | 'llm'
    If known formats don't match, or it's a binary, returns 'llm' so the llm_parser engine kicks in.
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
        return "llm" # let llm figure out unstructured/plain log

    # No extension — sniff content
    stripped = content.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return "json"
    if stripped.startswith("<") and "xml" in stripped[:100].lower():
        return "xml"
    if _looks_like_syslog(stripped):
        return "syslog"
    if _looks_like_csv(stripped):
        return "csv"
        
    return "llm"


def _looks_like_syslog(content: str) -> bool:
    """Matches RFC 3164 / RFC 5424 syslog patterns."""
    syslog_re = re.compile(
        r"^(?:<\d+>)?\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2}",
        re.MULTILINE,
    )
    iso_syslog_re = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*\w+\[\d+\]:",
        re.MULTILINE,
    )
    return bool(
        syslog_re.search(content[:2000]) or iso_syslog_re.search(content[:2000])
    )


def _looks_like_csv(content: str) -> bool:
    lines = [line for line in content.splitlines() if line.strip()][:5]
    if not lines:
        return False
    # Check that most lines have the same number of commas
    comma_counts = [line.count(",") for line in lines]
    return max(comma_counts) > 0 and len(set(comma_counts)) <= 2
