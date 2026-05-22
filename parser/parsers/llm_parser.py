"""
LLM-assisted parser for proprietary / unrecognised log formats.

Sends a small sample of the file content to OpenAI and asks it to
extract structured semiconductor log records.  Falls back to the
universal byte-safe parser if the LLM call fails for any reason.
"""

import json
import logging
import re
from typing import Generator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt — tells the LLM what we need
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert semiconductor equipment log analyst.

You will receive a sample of raw content from a proprietary log file used in a
semiconductor fabrication facility.  The file format is unknown — it may be
binary with embedded text, a custom structured format, or something else entirely.

Your task:
1. Identify the structure / pattern of the data.
2. Extract as many individual log records as you can find in the sample.
3. For each record, map fields to these STANDARD NAMES where possible:
   - timestamp       (ISO 8601 preferred)
   - tool_id         (equipment identifier, e.g. "ETCH-01")
   - severity        (one of: DEBUG, INFO, WARNING, ERROR, CRITICAL)
   - event_name      (what happened)
   - parameter_name  (sensor / setpoint name)
   - parameter_value (numeric reading)
   - unit            (measurement unit)
   - wafer_id        (lot or wafer identifier)
   - recipe_id       (process recipe name)
   - process_stage   (LOAD, PROCESS, PURGE, etc.)
   - alarm_code      (alarm / fault code if any)
   - raw_message     (the original unmodified text of this record)

Return ONLY a JSON array of objects.  Each object is one log record with the
fields above (omit fields that are not present — do not invent data).
No markdown fences, no preamble, no explanation — just the JSON array.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _prepare_sample(content_bytes: bytes, max_bytes: int = 4096) -> str:
    """
    Prepare a human-readable sample from raw bytes.

    For text-like content, decode as UTF-8.
    For binary content, produce a mixed hex + ASCII representation
    so the LLM can see embedded strings.
    """
    sample = content_bytes[:max_bytes]

    # Check if content is mostly text
    try:
        text = sample.decode("utf-8")
        # If decode succeeds cleanly, it's text
        return f"=== FILE SAMPLE (text, {len(sample)} bytes) ===\n{text}"
    except UnicodeDecodeError:
        pass

    # Mixed binary — show hex + ASCII side-by-side (like `hexdump -C`)
    lines = []
    lines.append(f"=== FILE SAMPLE (binary, {len(sample)} bytes) ===")
    for offset in range(0, len(sample), 16):
        chunk = sample[offset : offset + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset:08x}  {hex_part:<48s}  |{ascii_part}|")

    # Also extract printable strings (4+ chars) for extra context
    strings = re.findall(rb"[\x20-\x7e]{4,}", sample)
    if strings:
        lines.append("\n=== EMBEDDED STRINGS ===")
        for s in strings[:50]:
            lines.append(s.decode("ascii"))

    return "\n".join(lines)


def _call_llm(sample_text: str) -> str:
    """
    Send the sample to OpenAI and return the raw response text.
    Reuses the existing client from llm.analyzer.
    """
    from llm.analyzer import _call_chat

    return _call_chat(_SYSTEM_PROMPT, sample_text, max_tokens=4096)


def _parse_llm_response(raw_response: str) -> list[dict]:
    """
    Parse the LLM JSON response into a list of record dicts.
    Handles common formatting issues (markdown fences, trailing commas).
    """
    # Strip markdown code fences if present
    cleaned = raw_response.strip()
    cleaned = (
        cleaned.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    )

    # Try parsing directly
    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            # LLM might wrap in {"records": [...]}
            for key in ("records", "entries", "logs", "data"):
                if key in result and isinstance(result[key], list):
                    return result[key]
            # Single record
            return [result]
        return []
    except json.JSONDecodeError:
        pass

    # Try to extract a JSON array from the response
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.warning("LLM response could not be parsed as JSON")
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse(content_bytes: bytes) -> Generator[dict, None, None]:
    """
    Parse proprietary/unknown log content using the LLM.

    Sends a ~4 KB sample to OpenAI, receives structured records,
    and yields them as dicts compatible with the normaliser.

    Falls back to universal_parser on any failure.
    """
    sample_text = _prepare_sample(content_bytes)

    try:
        raw_response = _call_llm(sample_text)
        records = _parse_llm_response(raw_response)

        if not records:
            logger.warning("LLM returned no records, falling back to universal parser")
            yield from _fallback(content_bytes)
            return

        logger.info(f"LLM parser extracted {len(records)} records from sample")

        for record in records:
            # Ensure each record has at least raw_message
            if "raw_message" not in record:
                record["raw_message"] = json.dumps(record, default=str)
            yield record

    except Exception as e:
        logger.warning(f"LLM parser failed ({e}), falling back to universal parser")
        yield from _fallback(content_bytes)


def _fallback(content_bytes: bytes) -> Generator[dict, None, None]:
    """Fall back to the universal byte-safe parser."""
    from parser.parsers import universal_parser

    yield from universal_parser.parse(content_bytes)
