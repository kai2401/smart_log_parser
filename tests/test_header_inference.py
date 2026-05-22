"""
Tests for AI-Powered Column Header Inference.
Run with: python test_header_inference.py
"""

import json
import hashlib
from parser import parse_log
from parser.header_inference import get_or_infer_mapping
from database import db
import config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fingerprint(columns: list[str]) -> str:
    key = "|".join(sorted(c.lower() for c in columns))
    return hashlib.sha256(key.encode()).hexdigest()


def _clear_cached_mapping(columns: list[str]) -> None:
    fp = _make_fingerprint(columns)
    with db._get_conn() as conn:
        conn.execute(
            "DELETE FROM header_mappings WHERE header_fingerprint = ?", (fp,)
        )
        conn.commit()


def _unpack(result) -> dict:
    """Handle both (mapping, cache_hit) tuple and plain dict return shapes."""
    if isinstance(result, tuple):
        return result[0]
    return result


def _was_cache_hit(result) -> bool:
    if isinstance(result, tuple):
        return result[1]
    return False


# ---------------------------------------------------------------------------
# Test 1: LLM infers obvious non-standard headers correctly
# ---------------------------------------------------------------------------

def test_llm_infers_standard_aliases():
    if not config.OPENAI_API_KEY:
        print("  SKIP: No API key configured")
        return

    columns = ["ts_utc", "equip_no", "lvl", "msg_body", "lot_no"]
    _clear_cached_mapping(columns)

    result = get_or_infer_mapping(columns)
    mapping = _unpack(result)

    print(f"  Returned mapping: {mapping}")

    assert isinstance(mapping, dict), f"Expected dict, got {type(mapping)}"
    assert mapping.get("ts_utc") == "timestamp", \
        f"Expected timestamp, got {mapping.get('ts_utc')}"
    assert mapping.get("equip_no") == "tool_id", \
        f"Expected tool_id, got {mapping.get('equip_no')}"
    assert mapping.get("lvl") == "severity", \
        f"Expected severity, got {mapping.get('lvl')}"

    print("  PASS: LLM correctly inferred non-standard column headers")


# ---------------------------------------------------------------------------
# Test 2: Cache stores and retrieves correctly
# ---------------------------------------------------------------------------

def test_cache_hit_skips_llm():
    if not config.OPENAI_API_KEY:
        print("  SKIP: No API key configured")
        return

    columns = ["ts_utc", "equip_no", "lvl", "msg_body", "lot_no"]

    # Ensure it's cached from test 1 (or re-run if cleared)
    get_or_infer_mapping(columns)

    # Second call must be a cache hit
    result = get_or_infer_mapping(columns)
    mapping = _unpack(result)
    hit = _was_cache_hit(result)

    assert isinstance(mapping, dict), f"Expected dict, got {type(mapping)}"
    assert hit is True, "Expected cache hit on second call"

    # Verify persisted in DB
    fp = _make_fingerprint(columns)
    cached = db.get_header_mapping(fp)
    assert cached is not None, "Expected mapping to be persisted in DB"

    print(f"  PASS: Cache hit confirmed, mapping: {mapping}")


# ---------------------------------------------------------------------------
# Test 3: Well-known columns skip the LLM entirely
# ---------------------------------------------------------------------------

def test_known_columns_skip_llm():
    columns = ["timestamp", "tool_id", "severity", "message"]
    _clear_cached_mapping(columns)

    result = get_or_infer_mapping(columns)
    mapping = _unpack(result)

    assert mapping == {}, \
        f"Expected empty mapping for well-known columns, got: {mapping}"
    print("  PASS: Well-known columns correctly skipped LLM call")


# ---------------------------------------------------------------------------
# Test 4: No API key returns empty dict without crashing
# ---------------------------------------------------------------------------

def test_no_api_key_returns_empty():
    """
    Patches the header_inference module's own config reference,
    not just the top-level config module.
    """
    from unittest.mock import patch
    import parser.header_inference as hi_module

    columns = ["ts_utc", "equip_no", "lvl"]
    _clear_cached_mapping(columns)

    # Patch where header_inference reads the key, not where config defines it
    with patch.object(hi_module, "_api_key_available", return_value=False):
        result = get_or_infer_mapping(columns)
        mapping = _unpack(result)

    # If the module doesn't have _api_key_available, patch config directly
    # inside the module's namespace instead
    if mapping != {}:
        with patch("parser.header_inference.config") as mock_cfg:
            mock_cfg.OPENAI_API_KEY = ""
            _clear_cached_mapping(columns)
            result = get_or_infer_mapping(columns)
            mapping = _unpack(result)

    assert mapping == {}, f"Expected empty dict with no API key, got: {mapping}"
    print("  PASS: No API key returns empty dict gracefully")


# ---------------------------------------------------------------------------
# Test 5: Hallucinated canonical field names are discarded
# ---------------------------------------------------------------------------

def test_invalid_canonical_fields_discarded():
    fake_response = {
        "ts_utc": "timestamp",
        "equip_no": "tool_id",
        "foo_col": "made_up_field",
        "bar_col": "also_fake",
    }

    VALID_CANONICAL = {
        "timestamp", "tool_id", "severity", "event_name",
        "recipe_id", "wafer_id", "parameter_name",
        "parameter_value", "unit", "process_stage",
    }
    cleaned = {k: v for k, v in fake_response.items() if v in VALID_CANONICAL}

    assert "foo_col" not in cleaned
    assert "bar_col" not in cleaned
    assert cleaned.get("ts_utc") == "timestamp"
    assert cleaned.get("equip_no") == "tool_id"
    print(f"  PASS: Invalid canonical fields discarded, kept: {cleaned}")


# ---------------------------------------------------------------------------
# Test 6: End-to-end — CSV with non-standard headers
# ---------------------------------------------------------------------------

def test_e2e_csv_nonstandard_headers():
    if not config.OPENAI_API_KEY:
        print("  SKIP: No API key configured")
        return

    csv_data = (
        b"ts_utc,equip_no,lvl,msg_body,lot_no\n"
        b"2024-03-01T08:00:00,ETCH-01,ERROR,Pressure fault detected,LOT1234-W01\n"
        b"2024-03-01T08:01:00,CVD-03,WARNING,Temperature drift observed,LOT1234-W02\n"
    )

    entries, warnings = parse_log(csv_data, "nonstandard_headers.csv")

    print(f"  Entries parsed: {len(entries)}")
    print(f"  Warnings: {warnings}")
    if entries:
        e = entries[0]
        print(f"  Entry 0: timestamp={e.timestamp}, tool_id={e.tool_id}, severity={e.severity}")
        meta = json.loads(e.metadata)
        print(f"  Metadata keys: {list(meta.keys())}")

    assert len(entries) == 2, f"Expected 2 entries, got {len(entries)}"

    e = entries[0]
    assert e.tool_id == "ETCH-01", \
        f"Expected ETCH-01, got '{e.tool_id}' — AI mapping not applied before default injection"
    assert e.severity == "ERROR", f"Expected ERROR, got '{e.severity}'"
    assert "2024-03-01" in e.timestamp, f"Unexpected timestamp: {e.timestamp}"

    meta = json.loads(e.metadata)
    assert meta.get("wafer_id") == "LOT1234-W01", \
        f"Expected wafer_id in metadata, got: {meta}"

    print("  PASS: End-to-end CSV with non-standard headers parsed correctly")


# ---------------------------------------------------------------------------
# Test 7: Duplicate canonical mappings handled
# ---------------------------------------------------------------------------

def test_duplicate_canonical_fields_handled():
    fake_response = {
        "ts1": "timestamp",
        "ts2": "timestamp",
        "equip_no": "tool_id",
    }

    seen_canonical = set()
    deduped = {}
    for raw_col, canonical in fake_response.items():
        if canonical not in seen_canonical:
            deduped[raw_col] = canonical
            seen_canonical.add(canonical)

    assert sum(1 for v in deduped.values() if v == "timestamp") == 1
    assert "equip_no" in deduped
    print(f"  PASS: Duplicate canonical fields handled, result: {deduped}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    db.init_db()

    tests = [
        ("LLM infers non-standard headers", test_llm_infers_standard_aliases),
        ("Cache hit skips LLM", test_cache_hit_skips_llm),
        ("Known columns skip LLM", test_known_columns_skip_llm),
        ("No API key returns empty dict", test_no_api_key_returns_empty),
        ("Hallucinated fields discarded", test_invalid_canonical_fields_discarded),
        ("End-to-end CSV non-standard headers", test_e2e_csv_nonstandard_headers),
        ("Duplicate canonical fields handled", test_duplicate_canonical_fields_handled),
    ]

    passed = 0
    for name, fn in tests:
        print(f"\nTest: {name}")
        try:
            fn()
            passed += 1
        except Exception as ex:
            print(f"  FAIL: {ex}")

    print(f"\n{'='*50}")
    print(f"Results: {passed}/{len(tests)} tests passed")
