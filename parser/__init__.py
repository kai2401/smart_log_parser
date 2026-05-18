"""
Main parser pipeline:
  raw content  →  format detect  →  format parser  →  normaliser  →  [LogEntry]
"""

from parser.detector import detect_format
from parser.normalizer import normalise_record
from parser.schema import LogEntry
import io
import pandas as pd
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


def parse_log(content_bytes: bytes, filename: str) -> tuple[list[LogEntry], list[str]]:
    """
    Parse raw log content into a list of LogEntry objects.

    Returns:
        entries  – successfully parsed and normalised entries
        warnings – list of human-readable warnings about skipped/invalid records
    """
    if filename.lower().endswith(".parquet"):
        try:
            df = pd.read_parquet(io.BytesIO(content_bytes))
            raw_records = df.to_dict(orient="records")
            entries: list[LogEntry] = []
            warnings: list[str] = []
            for i, raw in enumerate(raw_records):
                try:
                    normalised = normalise_record(
                        raw, source_format="parquet", filename=filename
                    )
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
        except Exception as e:
            return [], [f"Failed to decode Parquet file {filename}: {e}"]

    fmt = detect_format(filename, content_bytes)
    
    entries: list[LogEntry] = []
    warnings: list[str] = []

    try:
        if fmt in FORMAT_PARSERS:
            parser_module = FORMAT_PARSERS[fmt]
            content_str = content_bytes.decode("utf-8", errors="replace")
            raw_records = list(parser_module.parse(content_str))
            
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
                    
        else:
            # Fallback to LLM parser engine for custom/binary/unstructured formats
            remapped_records, format_info, field_map, llm_called = parse_with_llm(content_bytes, filename)
            fmt = format_info.get("format_name", "unknown")
            
            for i, raw in enumerate(remapped_records):
                try:
                    # Pass the already-remapped record safely
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
            
    except Exception as e:
        warnings.append(f"Parser failed for format '{fmt}': {e}")
        return entries, warnings

    return entries, warnings
