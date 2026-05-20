"""Quick smoke test for the refactored Smart Hybrid pipeline."""

import json
from parser import parse_log


def test_json_no_timestamp():
    """Missing timestamp should NOT crash — defaults to now()."""
    data = json.dumps([
        {"tool_id": "ETX01", "severity": "ERROR", "message": "Vacuum failure"}
    ]).encode()
    entries, warnings = parse_log(data, "test.json")
    assert len(entries) == 1, f"Expected 1 entry, got {len(entries)}"
    e = entries[0]
    assert e.timestamp is not None and e.timestamp != "", "Timestamp should default to now()"
    assert e.tool_id == "ETX01"
    assert e.severity == "ERROR"
    print(f"  PASS: timestamp={e.timestamp[:19]}, tool_id={e.tool_id}")


def test_kv_format():
    """Key=value lines should be detected and parsed."""
    data = b"tool_id=ETX02 pressure=5.2 temperature=350 severity=WARNING"
    entries, warnings = parse_log(data, "readings.log")
    assert len(entries) >= 1, f"Expected >=1 entry, got {len(entries)}"
    print(f"  PASS: {len(entries)} entries from KV format")


def test_invalid_file_rejected():
    """PNG file should be rejected by guardrails."""
    entries, warnings = parse_log(b"fake image data", "photo.png")
    assert len(entries) == 0, "PNG should be rejected"
    assert len(warnings) > 0, "Should have a warning about invalid format"
    print(f"  PASS: rejected with warning: {warnings[0]}")


def test_recipe_detection():
    """Files with 'recipe' in the name should get log_type='recipe'."""
    data = json.dumps([
        {"recipe_id": "RCP-001", "parameter_name": "temperature", "value": 400}
    ]).encode()
    entries, warnings = parse_log(data, "recipe_config.json")
    assert len(entries) >= 1
    e = entries[0]
    assert e.log_type == "recipe", f"Expected log_type='recipe', got '{e.log_type}'"
    print(f"  PASS: log_type={e.log_type}, recipe_id={e.recipe_id}")


def test_best_effort_defaults():
    """Completely bare JSON should still produce a valid entry with defaults."""
    data = json.dumps([{"foo": "bar"}]).encode()
    entries, warnings = parse_log(data, "unknown.json")
    assert len(entries) == 1
    e = entries[0]
    assert e.timestamp is not None and len(e.timestamp) > 0
    assert e.tool_id is not None and len(e.tool_id) > 0
    assert e.severity == "INFO"
    print(f"  PASS: timestamp={e.timestamp[:10]}..., tool_id={e.tool_id}, severity={e.severity}")


def test_csv_parse():
    """CSV with headers should parse correctly."""
    csv_data = b"timestamp,tool_id,severity,message\n2024-01-15T10:00:00,ETX03,ERROR,Pump fault detected"
    entries, warnings = parse_log(csv_data, "logs.csv")
    assert len(entries) == 1
    e = entries[0]
    assert e.tool_id == "ETX03"
    assert e.severity == "ERROR"
    print(f"  PASS: tool_id={e.tool_id}, severity={e.severity}")


if __name__ == "__main__":
    tests = [
        ("JSON with missing timestamp", test_json_no_timestamp),
        ("KV format detection", test_kv_format),
        ("Invalid file rejection", test_invalid_file_rejected),
        ("Recipe file detection", test_recipe_detection),
        ("Best-effort defaults", test_best_effort_defaults),
        ("CSV parsing", test_csv_parse),
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
