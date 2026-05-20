"""
Main parser pipeline — Smart Hybrid architecture:
  raw content  →  guardrail check  →  deterministic dispatch  →  format parser  →  normaliser  →  [LogEntry|RecipeEntry]

No LLM code-generation in the hot path. Deterministic, robust, and schema-adaptive.
"""

import re
import io
import pandas as pd

from parser.detector import detect_format
from parser.normalizer import normalise_record
from parser.schema import LogEntry, RecipeEntry
from parser.parsers import (
    json_parser,
    csv_parser,
    xml_parser,
    kv_parser,
    syslog_parser,
    text_parser,
)

FORMAT_PARSERS = {
    "json": json_parser,
    "csv": csv_parser,
    "xml": xml_parser,
    "kv": kv_parser,
    "syslog": syslog_parser,
    "text": text_parser,
}


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------

def is_valid_log_file(content_bytes: bytes, filename: str) -> bool:
    """
    Reject obviously invalid files before they enter the pipeline.
    Checks: non-log extensions, emoji/ASCII-art content, and
    semiconductor fab domain relevance.
    """
    fname_lower = filename.lower()

    # Hard rejection of non-log binaries
    if fname_lower.endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg',
                             '.pdf', '.docx', '.xlsx', '.pptx',
                             '.exe', '.dll', '.msi',
                             '.zip', '.tar', '.gz', '.7z', '.rar',
                             '.mp3', '.mp4', '.avi', '.mov', '.wav')):
        return False

    # Sample first 1 KB for heuristics
    sample = content_bytes[:1024].decode('utf-8', errors='ignore')

    # Emoji rejection (fab logs should have essentially none)
    if len(re.findall(r"[\U00010000-\U0010ffff]", sample)) > 2:
        return False

    # ASCII art / decorative text rejection
    ascii_art_patterns = [
        r"[═║╔╗╚╝╠╣╦╩╬]{3,}",
        r"[─│┌┐└┘├┤┬┴┼]{5,}",
        r"[*#=\-~_]{10,}",
        r"[░▒▓█]{3,}",
        r"[♠♣♥♦★☆●○◆◇]{3,}",
    ]
    art_hits = sum(1 for p in ascii_art_patterns if re.search(p, sample))
    if art_hits >= 2:
        return False

    # Semiconductor fab relevance gate
    extended = content_bytes[:4096].decode('utf-8', errors='ignore').lower()
    fab_keywords = [
        r"\btool[_\s]?id\b", r"\bmachine", r"\bequip", r"\bchamber\b",
        r"\bwafer\b", r"\brecipe\b", r"\bsetpoint\b", r"\blot",
        r"\bpressure\b", r"\btemperature\b", r"\bvacuum\b", r"\btorr\b",
        r"\brpm\b", r"\bsccm\b", r"\bvoltage\b", r"\bcurrent\b", r"\bpower\b",
        r"\b(info|warn|error|critical|debug|fault|alarm)\b",
        r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}",
        r"\btimestamp\b", r"\bseverity\b", r"\bsensor\b",
        r"\betch\b", r"\bdeposit\b", r"\bcvd\b", r"\bpvd\b",
        r"\bsubstrate\b", r"\bfoup\b", r"\bloadlock\b",
        r"\bmaintenan", r"\bcalibrat", r"\brf[_\s]?power\b",
    ]
    fab_hits = sum(1 for kw in fab_keywords if re.search(kw, extended))
    if fab_hits < 2:
        # Last chance: valid extension + structured data markers
        valid_ext = fname_lower.endswith(('.log', '.txt', '.csv', '.json',
                                          '.xml', '.tsv', '.parquet'))
        if valid_ext:
            markers = [r"\d{4}-\d{2}-\d{2}", r"\{.*\}", r"<.*>",
                       r"ERROR|INFO|WARN|DEBUG", r"\[.*\]"]
            if any(re.search(m, sample, re.IGNORECASE) for m in markers):
                return True
        return False

    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_log(
    content_bytes: bytes,
    filename: str,
) -> tuple[list[LogEntry], list[str]]:
    """
    Parse raw log content into a list of LogEntry objects.

    Smart Hybrid pipeline:
      1. Guardrail validation
      2. Deterministic format dispatch (extension → content sniff → kv fallback)
      3. Best-effort normalisation (no crash on missing fields)

    Returns:
        entries  – successfully parsed and normalised entries
        warnings – list of human-readable warnings about skipped/invalid records
    """
    # ── Guard: reject junk files ────────────────────────────────────────
    if not is_valid_log_file(content_bytes, filename):
        return [], [f"Invalid file format: {filename}"]

    # ── Detect if this is a recipe file ─────────────────────────────────
    is_recipe = 'recipe' in filename.lower()

    # ── Parquet fast-path (binary, needs special reader) ────────────────
    if filename.lower().endswith(".parquet"):
        return _parse_parquet(content_bytes, filename, is_recipe)

    # ── Deterministic format dispatch ───────────────────────────────────
    content_str = content_bytes.decode("utf-8", errors="replace")
    fmt = _detect_format_smart(filename, content_bytes, content_str)

    entries: list[LogEntry] = []
    warnings: list[str] = []

    try:
        if fmt in FORMAT_PARSERS:
            parser_module = FORMAT_PARSERS[fmt]
            raw_records = list(parser_module.parse(content_str))

            for i, raw in enumerate(raw_records):
                try:
                    normalised = normalise_record(
                        raw,
                        source_format=fmt,
                        filename=filename,
                        is_recipe=is_recipe,
                    )
                    entry = _build_entry(normalised, is_recipe)
                    _validate_and_warn(entry, i, warnings)
                    entries.append(entry)
                except Exception as e:
                    warnings.append(f"Row {i + 1}: normalisation error — {e}")
        else:
            warnings.append(
                f"No deterministic parser found for format '{fmt}' in {filename}. "
                f"Falling back to universal byte-safe parser."
            )
            # Ultimate fallback: universal parser
            from parser.parsers import universal_parser
            raw_records = list(universal_parser.parse(content_bytes))
            for i, raw in enumerate(raw_records):
                try:
                    normalised = normalise_record(
                        raw,
                        source_format="universal",
                        filename=filename,
                        is_recipe=is_recipe,
                    )
                    entry = _build_entry(normalised, is_recipe)
                    _validate_and_warn(entry, i, warnings)
                    entries.append(entry)
                except Exception as e:
                    warnings.append(f"Row {i + 1}: normalisation error — {e}")

    except Exception as e:
        warnings.append(f"Parser failed for format '{fmt}': {e}")
        return entries, warnings

    return entries, warnings


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _detect_format_smart(
    filename: str,
    content_bytes: bytes,
    content_str: str,
) -> str:
    """
    Enhanced deterministic format detection.
    Adds KV detection on top of the existing detector logic.
    Falls back to text parser instead of LLM.
    """
    fmt = detect_format(filename, content_bytes)

    # If the standard detector couldn't match, try KV heuristic
    if fmt == "llm":
        # Check for key=value patterns in the first 500 chars
        sample = content_str[:500]
        kv_hits = len(re.findall(r"[\w.\-]+\s*[=:]\s*\S+", sample))
        if kv_hits >= 2:
            return "kv"
        # Final fallback: universal byte-safe
        return "universal"

    return fmt


def _parse_parquet(
    content_bytes: bytes,
    filename: str,
    is_recipe: bool,
) -> tuple[list[LogEntry], list[str]]:
    """Handle Parquet files via pandas."""
    entries: list[LogEntry] = []
    warnings: list[str] = []
    try:
        df = pd.read_parquet(io.BytesIO(content_bytes))
        raw_records = df.to_dict(orient="records")

        for i, raw in enumerate(raw_records):
            try:
                normalised = normalise_record(
                    raw,
                    source_format="parquet",
                    filename=filename,
                    is_recipe=is_recipe,
                )
                entry = _build_entry(normalised, is_recipe)
                _validate_and_warn(entry, i, warnings)
                entries.append(entry)
            except Exception as e:
                warnings.append(f"Row {i + 1}: normalisation error — {e}")
        return entries, warnings
    except Exception as e:
        return [], [f"Failed to decode Parquet file {filename}: {e}"]


def _build_entry(normalised: dict, is_recipe: bool) -> LogEntry:
    """
    Construct a LogEntry from normalised dict.
    Filters keys to only those that exist on the dataclass.
    """
    return LogEntry(
        **{
            k: v
            for k, v in normalised.items()
            if k in LogEntry.__dataclass_fields__
        }
    )


def _validate_and_warn(entry: LogEntry, index: int, warnings: list[str]) -> None:
    """Check mandatory fields and append warnings (but never reject)."""
    valid, missing = entry.is_valid()
    if not valid:
        warnings.append(
            f"Row {index + 1}: missing mandatory fields {missing} — saved anyway"
        )
