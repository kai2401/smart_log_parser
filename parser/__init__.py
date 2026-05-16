"""
Main parser pipeline:
  raw content  →  format detect  →  format parser  →  normaliser  →  [LogEntry]
"""

from parser.detector import detect_format
from parser.normalizer import normalise_record
from parser.schema import LogEntry
from parser.parsers import (
    json_parser,
    csv_parser,
    xml_parser,
    syslog_parser,
    text_parser,
)

FORMAT_PARSERS = {
    "json": json_parser,
    "csv": csv_parser,
    "xml": xml_parser,
    "syslog": syslog_parser,
    "text": text_parser,
}


def parse_log(content: str, filename: str) -> tuple[list[LogEntry], list[str]]:
    """
    Parse raw log content into a list of LogEntry objects.

    Returns:
        entries  – successfully parsed and normalised entries
        warnings – list of human-readable warnings about skipped/invalid records
    """
    fmt = detect_format(filename, content)
    parser_module = FORMAT_PARSERS.get(fmt, text_parser)

    entries: list[LogEntry] = []
    warnings: list[str] = []

    try:
        raw_records = list(parser_module.parse(content))
    except Exception as e:
        warnings.append(f"Parser failed for format '{fmt}': {e}")
        return entries, warnings

    for i, raw in enumerate(raw_records):
        try:
            normalised = normalise_record(raw, source_format=fmt, filename=filename)
            entry = LogEntry(
                **{
                    k: v
                    for k, v in normalised.items()
                    if hasattr(LogEntry, k) or k in LogEntry.__dataclass_fields__
                }
            )
            valid, missing = entry.is_valid()
            if not valid:
                warnings.append(
                    f"Row {i + 1}: missing mandatory fields {missing} — saved anyway"
                )
            entries.append(entry)
        except Exception as e:
            warnings.append(f"Row {i + 1}: normalisation error — {e}")

    return entries, warnings
