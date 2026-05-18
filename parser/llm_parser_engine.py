"""
llm_parser_engine.py

Three LLM calls, each paid once per novel format, cached forever:

  Call 1 (~200 tok)  identify format from hex dump
  Call 2 (~900 tok)  generate parse() function
  Call 3 (~400 tok)  map raw field names -> LogEntry schema fields

Everything is stored in .parser_cache.json keyed by a fingerprint of the
first 512 bytes.  Cache hits cost zero tokens.
"""

from __future__ import annotations

import hashlib
import json
import os
import types
from typing import Any

import openai

_client = openai.OpenAI()
MODEL = "gpt-4o"

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_CACHE_PATH = os.path.join(os.path.dirname(__file__), ".parser_cache.json")
_CACHE: dict[str, dict] = {}


def _load_cache() -> None:
    global _CACHE
    if os.path.exists(_CACHE_PATH):
        try:
            with open(_CACHE_PATH) as f:
                _CACHE = json.load(f)
        except (json.JSONDecodeError, OSError):
            _CACHE = {}


def _save_cache() -> None:
    try:
        with open(_CACHE_PATH, "w") as f:
            json.dump(_CACHE, f, indent=2)
    except OSError:
        pass


_load_cache()


def _fingerprint(header: bytes) -> str:
    return hashlib.sha256(header).hexdigest()[:8]


# ---------------------------------------------------------------------------
# Hex dump helper
# ---------------------------------------------------------------------------

def _hex_dump(data: bytes, n: int = 512) -> str:
    rows = []
    for i in range(0, min(len(data), n), 16):
        chunk = data[i : i + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        asc_part = "".join(chr(b) if 0x20 <= b <= 0x7E else "." for b in chunk)
        rows.append(f"{i:04x}  {hex_part:<47}  {asc_part}")
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Call 1: format identification
# ---------------------------------------------------------------------------

_IDENTIFY_SYSTEM = """\
You are a binary and text format analyst specialised in log file formats.

Given an xxd-style hex dump of the first bytes of a file, identify the format.
Return ONLY valid JSON - no markdown, no fences, no commentary.

Required fields:
{
  "format_name":      "<slug: e.g. pipe_csv / msgpack / custom_tlv / parquet>",
  "description":      "<one sentence>",
  "is_binary":        true | false,
  "record_delimiter": "<newline | null | length_prefix | fixed<N> | implicit>",
  "field_delimiter":  "<comma | tab | pipe | fixed_width | N/A>",
  "has_header":       true | false,
  "encoding":         "<utf-8 | ascii | latin-1 | binary>",
  "confidence":       0.0-1.0,
  "notes":            "<anything the parser generator needs>"
}

Be precise about record_delimiter:
  newline       = newline or CRLF between records
  null          = 0x00 byte between records
  length_prefix = each record preceded by a 2- or 4-byte integer length
  fixed<N>      = every record is exactly N bytes (e.g. fixed128)
  implicit      = format-specific (e.g. MessagePack: read until next valid tag)

Set format_name to "unknown" and confidence < 0.5 if you cannot identify it.\
"""


def _llm_identify(header_bytes: bytes) -> dict:
    dump = _hex_dump(header_bytes)
    msg = _client.chat.completions.create(
        model=MODEL,
        max_tokens=400,
        messages=[
            {"role": "system", "content": _IDENTIFY_SYSTEM},
            {"role": "user", "content": f"Hex dump:\n\n{dump}"}
        ],
    )
    raw = msg.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError as e:
        raise ValueError(f"Call 1 returned invalid JSON: {e}\nRaw: {raw!r}")


# ---------------------------------------------------------------------------
# Call 2: parser generation
# ---------------------------------------------------------------------------

_GENERATE_SYSTEM = """\
You are a Python expert writing a log file parser.

You will receive a format description (JSON) and a hex dump of the file header.

Write a single Python source file containing:
  (a) A module docstring describing the format
  (b) A generator called `parse(content)` - content is bytes if is_binary else str

Rules:
  IMPORTS   - standard library only (struct, io, csv, re, json, etc.)
              No third-party packages. Implement binary decoding yourself.
  YIELDS    - one plain dict per logical record
  KEYS      - use the actual field/column names from the file, lowercased, snake_cased.
              If names are unknown (positional binary fields) use field_01, field_02 ...
  ERRORS    - skip malformed individual records (continue); raise ValueError for fatal
              format errors (wrong magic, truncated header, etc.)
  ROBUSTNESS - handle both newline and CRLF; strip whitespace from string values

Output ONLY raw Python source. No markdown fences. No explanation.\
"""


def _llm_generate_parser(format_info: dict, header_bytes: bytes) -> str:
    dump = _hex_dump(header_bytes, n=256)
    prompt = (
        f"Format description:\n{json.dumps(format_info, indent=2)}\n\n"
        f"Hex dump (first 256 bytes):\n\n{dump}\n\n"
        "Write parse(content) now."
    )
    msg = _client.chat.completions.create(
        model=MODEL,
        max_tokens=1500,
        messages=[
            {"role": "system", "content": _GENERATE_SYSTEM},
            {"role": "user", "content": prompt}
        ],
    )
    code = msg.choices[0].message.content.strip()
    if code.startswith("```"):
        lines = code.splitlines()
        code = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return code.strip()


# ---------------------------------------------------------------------------
# Call 3: field mapping
# ---------------------------------------------------------------------------

_SCHEMA_DESCRIPTION = """\
Target LogEntry schema fields and their meaning:

  timestamp        ISO-8601 datetime. Any date/time field in the source.
  tool_id          Machine, device, equipment, host, or system identifier.
  severity         One of: DEBUG | INFO | WARNING | ERROR | CRITICAL
                   Map any priority/level/importance/alarm_type field here.
  log_type         One of: process_step | alarm | sensor_reading | maintenance | info
                   Infer from context if not an explicit field.
  event_name       Human-readable description of what happened.
                   Map: message, msg, description, action, operation, detail, text, event ...
  recipe_id        Process recipe or job identifier.
  wafer_id         Wafer, lot, substrate, or batch identifier.
  process_stage    Stage name, step name, phase, or operation phase (string).
  step_number      Integer step or sequence number.
  parameter_name   Sensor or parameter name (e.g. temperature, pressure, flow_rate).
  parameter_value  Numeric sensor reading (float).
  unit             Unit of measurement (Torr, RPM, C, %, V, A, W ...).
  raw_message      Catch-all for any field that does not fit elsewhere.
                   MULTIPLE fields can map here - they will be concatenated.
                   Always populate this - it is a mandatory field.

DO NOT map to: id, source_format, source_filename, normalized_message,
               ai_summary, ai_classification, ai_root_cause_hint
               (these are auto-populated by the pipeline)\
"""

_MAP_SYSTEM = f"""\
You are a data mapping expert for semiconductor equipment log normalisation.

You will receive:
  1. A list of raw field names from a novel log format
  2. Sample records showing actual values for each field
  3. The target schema definition

Your job: output a JSON object mapping every raw field name to the most
appropriate LogEntry schema field name.

{_SCHEMA_DESCRIPTION}

Mapping rules:
  - Every raw field name must appear as a key. No omissions.
  - If a field maps clearly to a schema field, use that schema field as the value.
  - If a field does not map to any schema field, set its value to "raw_message".
    Multiple fields can all map to "raw_message" - they get concatenated later.
  - For numeric sensor values, map the value field to "parameter_value" and the
    corresponding name field (if separate) to "parameter_name".
  - Severity: map any level/priority/importance/alarm field to "severity" even if
    the values are non-standard (e.g. FAULT, P1, HIGH) - the normaliser handles conversion.
  - Only use schema field names listed above. Do not invent new ones.

Return ONLY valid JSON. No markdown, no fences, no commentary.

Example for a file with fields ts, eq_id, lvl, msg_text, lot_no, proc_recipe, temp_c, s_name:
{{
  "ts":          "timestamp",
  "eq_id":       "tool_id",
  "lvl":         "severity",
  "msg_text":    "event_name",
  "lot_no":      "wafer_id",
  "proc_recipe": "recipe_id",
  "temp_c":      "parameter_value",
  "s_name":      "parameter_name"
}}\
"""


def _llm_map_fields(
    raw_field_names: list[str],
    sample_records: list[dict],
) -> dict[str, str]:
    sample_lines = []
    for rec in sample_records[:5]:
        row = ", ".join(f"{k}={repr(str(v))[:40]}" for k, v in rec.items())
        sample_lines.append(f"  {row}")

    prompt = (
        f"Raw field names: {json.dumps(raw_field_names)}\n\n"
        f"Sample records (first 5):\n" + "\n".join(sample_lines)
    )

    msg = _client.chat.completions.create(
        model=MODEL,
        max_tokens=600,
        messages=[
            {"role": "system", "content": _MAP_SYSTEM},
            {"role": "user", "content": prompt}
        ],
    )
    raw = msg.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        mapping = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        raise ValueError(f"Call 3 returned invalid JSON: {e}\nRaw: {raw!r}")

    for f in raw_field_names:
        if f not in mapping:
            mapping[f] = "raw_message"

    return mapping


# ---------------------------------------------------------------------------
# Compile + smoke test
# ---------------------------------------------------------------------------

def _compile_parser(code: str, format_name: str) -> types.ModuleType:
    namespace: dict = {
        "__builtins__": __builtins__,
        "__name__": f"llm_parser_{format_name}",
    }
    try:
        exec(compile(code, f"<llm_parser_{format_name}>", "exec"), namespace)
    except SyntaxError as e:
        raise ValueError(f"Generated parser has syntax error: {e}\n\nCode:\n{code}")

    if not callable(namespace.get("parse")):
        raise ValueError(
            "Generated code has no callable `parse`. "
            f"Defined names: {[k for k in namespace if not k.startswith('_')]}"
        )

    mod = types.ModuleType(f"llm_parser_{format_name}")
    mod.__dict__.update(namespace)
    return mod


def _smoke_test(
    mod: types.ModuleType, sample: bytes, is_binary: bool
) -> list[dict]:
    arg = sample if is_binary else sample.decode("utf-8", errors="replace")
    try:
        records = []
        for i, rec in enumerate(mod.parse(arg)):
            if not isinstance(rec, dict):
                raise ValueError(
                    f"parse() yielded {type(rec).__name__}, expected dict"
                )
            records.append(rec)
            if i >= 9:
                break
        if not records:
            raise ValueError("parse() yielded no records from sample data")
        return records
    except StopIteration:
        raise ValueError("parse() raised StopIteration instead of yielding")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"parse() raised {type(e).__name__} during smoke test: {e}")


# ---------------------------------------------------------------------------
# Correction loop (fired when smoke test fails)
# ---------------------------------------------------------------------------

_CORRECT_SYSTEM = """\
You are debugging a Python log parser that failed during testing.

You receive the format description, the broken parser code, the error message,
and the hex dump of the data it failed on.

Fix the parser. Return ONLY corrected Python source. No fences, no explanation.\
"""


def _llm_correct_parser(
    format_info: dict, bad_code: str, error: str, header_bytes: bytes
) -> str:
    dump = _hex_dump(header_bytes, n=256)
    prompt = (
        f"Format:\n{json.dumps(format_info, indent=2)}\n\n"
        f"Broken code:\n{bad_code}\n\n"
        f"Error:\n{error}\n\n"
        f"Hex dump:\n{dump}\n\nFix it."
    )
    msg = _client.chat.completions.create(
        model=MODEL,
        max_tokens=1500,
        messages=[
            {"role": "system", "content": _CORRECT_SYSTEM},
            {"role": "user", "content": prompt}
        ],
    )
    code = msg.choices[0].message.content.strip()
    if code.startswith("```"):
        lines = code.splitlines()
        code = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return code.strip()


# ---------------------------------------------------------------------------
# Applying the field map
# ---------------------------------------------------------------------------

def apply_field_map(raw: dict, field_map: dict[str, str]) -> dict:
    out: dict[str, Any] = {}
    raw_message_parts: list[str] = []

    for raw_key, raw_val in raw.items():
        schema_field = field_map.get(raw_key, "raw_message")

        if schema_field == "raw_message":
            raw_message_parts.append(f"{raw_key}={raw_val}")
        elif schema_field in out:
            raw_message_parts.append(f"{raw_key}={raw_val}")
        else:
            out[schema_field] = raw_val

    if raw_message_parts:
        existing = out.get("raw_message", "")
        combined = " | ".join(raw_message_parts)
        out["raw_message"] = f"{existing} | {combined}".lstrip(" | ") if existing else combined

    return out


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

MAX_RETRIES = 2


def get_parser(
    content: bytes,
    filename: str = "",
) -> tuple[types.ModuleType, dict, dict[str, str], bool]:
    header = content[:512]
    fp = _fingerprint(header)

    if fp in _CACHE:
        entry = _CACHE[fp]
        mod = _compile_parser(entry["parser_code"], entry["format_name"])
        return mod, entry["format_info"], entry["field_map"], False

    format_info = _llm_identify(header)
    if format_info.get("confidence", 0) < 0.5:
        raise ValueError(
            f"LLM could not identify format "
            f"(confidence={format_info.get('confidence', 0):.2f}). "
            "Register a proprietary parser manually for this format."
        )

    parser_code: str = ""
    sample_records: list[dict] = []
    last_error = ""

    for attempt in range(MAX_RETRIES + 1):
        if attempt == 0:
            parser_code = _llm_generate_parser(format_info, header)
        else:
            parser_code = _llm_correct_parser(
                format_info, parser_code, last_error, header
            )

        try:
            mod = _compile_parser(parser_code, format_info["format_name"])
            sample_records = _smoke_test(
                mod, content[:4096], format_info.get("is_binary", True)
            )
            break
        except ValueError as e:
            last_error = str(e)
            if attempt == MAX_RETRIES:
                raise ValueError(
                    f"Parser generation failed after {MAX_RETRIES + 1} attempts. "
                    f"Last error: {last_error}"
                ) from e

    all_raw_keys = list({k for rec in sample_records for k in rec.keys()})
    field_map = _llm_map_fields(all_raw_keys, sample_records)

    _CACHE[fp] = {
        "format_name": format_info["format_name"],
        "format_info": format_info,
        "parser_code": parser_code,
        "field_map":   field_map,
    }
    _save_cache()

    return mod, format_info, field_map, True


def parse_with_llm(
    content: bytes,
    filename: str = "",
) -> tuple[list[dict], dict, dict[str, str], bool]:
    mod, format_info, field_map, llm_called = get_parser(content, filename)
    is_binary = format_info.get("is_binary", True)
    arg = content if is_binary else content.decode("utf-8", errors="replace")

    remapped = [apply_field_map(rec, field_map) for rec in mod.parse(arg)]
    return remapped, format_info, field_map, llm_called


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------

def list_cached_formats() -> list[dict]:
    return [
        {
            "fingerprint": fp,
            "format_name": v["format_name"],
            "description": v.get("format_info", {}).get("description", ""),
            "confidence":  v.get("format_info", {}).get("confidence"),
            "field_map":   v.get("field_map", {}),
        }
        for fp, v in _CACHE.items()
    ]


def get_cached_parser_code(fingerprint: str) -> str | None:
    entry = _CACHE.get(fingerprint)
    return entry["parser_code"] if entry else None


def get_cached_field_map(fingerprint: str) -> dict[str, str] | None:
    entry = _CACHE.get(fingerprint)
    return entry.get("field_map") if entry else None


def replace_cached_parser(fingerprint: str, new_code: str) -> None:
    entry = _CACHE.get(fingerprint)
    if not entry:
        raise KeyError(f"No cached entry for fingerprint {fingerprint!r}")
    _compile_parser(new_code, entry["format_name"])
    _CACHE[fingerprint]["parser_code"] = new_code
    _save_cache()


def replace_cached_field_map(
    fingerprint: str, new_map: dict[str, str]
) -> None:
    entry = _CACHE.get(fingerprint)
    if not entry:
        raise KeyError(f"No cached entry for fingerprint {fingerprint!r}")
    _CACHE[fingerprint]["field_map"] = new_map
    _save_cache()


def evict_cache(fingerprint: str | None = None) -> int:
    global _CACHE
    if fingerprint:
        removed = int(fingerprint in _CACHE)
        _CACHE.pop(fingerprint, None)
    else:
        removed = len(_CACHE)
        _CACHE = {}
    _save_cache()
    return removed
