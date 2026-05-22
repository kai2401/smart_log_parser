"""
Verification script for unmapped column warning feature.
Run with: python check_unmapped.py
"""
import json
from parser import parse_log
from database import db

db.init_db()

with open("test_unmapped.csv", "rb") as f:
    content = f.read()

print("=" * 55)
print("TEST: Unmapped Column Warning")
print("=" * 55)

entries, warnings = parse_log(content, "test_unmapped.csv")

# ── Check 1: Entries parsed ──────────────────────────────
print(f"\n[1] Entries parsed: {len(entries)}")
assert len(entries) == 3, f"Expected 3, got {len(entries)}"
print("    PASS")

# ── Check 2: Warning was emitted ─────────────────────────
print(f"\n[2] Warnings returned: {len(warnings)}")
for w in warnings:
    print(f"    → {w}")

inference_warnings = [w for w in warnings if "AI header inference" in w]
assert len(inference_warnings) == 1, (
    f"Expected exactly 1 inference warning, got {len(inference_warnings)}.\n"
    f"All warnings: {warnings}"
)
print("    PASS: Exactly one inference warning emitted")

# ── Check 3: Warning names the unmapped columns ──────────
warning_text = inference_warnings[0]
print(f"\n[3] Warning content:\n    {warning_text}")

expected_unmapped = ["xrf_coeff_delta", "proc_bias_offset", "quantum_yield_pct"]
for col in expected_unmapped:
    assert col in warning_text, (
        f"Expected '{col}' to be named in warning.\nWarning was: {warning_text}"
    )
print("    PASS: All unmapped columns named in warning")

# ── Check 4: Warning NOT emitted for mapped columns ──────
print("\n[4] Checking mapped columns not reported as unmapped...")
mapped_cols = ["ts_utc", "equip_no", "lvl", "msg_body", "lot_no"]
for col in mapped_cols:
    assert col not in warning_text, (
        f"'{col}' was successfully mapped but appears in unmapped warning"
    )
print("    PASS: Mapped columns not reported as unmapped")

# ── Check 5: Unmapped columns stored in metadata ─────────
print("\n[5] Checking unmapped columns stored in metadata...")
e = entries[0]
meta = json.loads(e.metadata)
print(f"    Metadata keys: {list(meta.keys())}")

assert "ai_unmapped_columns" in meta, (
    f"Expected 'ai_unmapped_columns' in metadata, got keys: {list(meta.keys())}"
)
stored_unmapped = meta["ai_unmapped_columns"]
print(f"    Stored unmapped: {stored_unmapped}")

for col in expected_unmapped:
    assert col in stored_unmapped, (
        f"Expected '{col}' in metadata ai_unmapped_columns, got: {stored_unmapped}"
    )
print("    PASS: Unmapped columns stored in metadata")

# ── Check 6: Unmapped values still preserved ─────────────
print("\n[6] Checking unmapped column values still preserved...")
assert "xrf_coeff_delta" in meta, (
    f"Expected raw value of xrf_coeff_delta in metadata, not found.\nMetadata: {meta}"
)
print(f"    xrf_coeff_delta value: {meta.get('xrf_coeff_delta')}")
print("    PASS: Unmapped column values preserved in metadata")

# ── Check 7: Mapped fields correctly extracted ───────────
print("\n[7] Checking mapped fields on entry...")
assert e.tool_id == "ETCH-01", f"Expected ETCH-01, got '{e.tool_id}'"
assert e.severity == "ERROR",  f"Expected ERROR, got '{e.severity}'"
assert "2024-03-01" in e.timestamp
print(f"    tool_id   : {e.tool_id}")
print(f"    severity  : {e.severity}")
print(f"    timestamp : {e.timestamp}")
print("    PASS: Mapped fields correctly extracted")

# ── Check 8: Warning emitted only once, not per row ──────
print("\n[8] Checking warning emitted once not per row...")
assert len(inference_warnings) == 1, (
    f"Expected 1 warning for 3 rows, got {len(inference_warnings)}"
)
print("    PASS: Warning deduplicated across rows")

# ── Check 9: DB query for unmapped columns works ─────────
print("\n[9] Checking DB query for unmapped columns...")
with db._get_conn() as conn:
    result = conn.execute(
        """
        SELECT DISTINCT json_extract(metadata, '$.ai_unmapped_columns')
        FROM log_entries
        WHERE source_filename = ?
        AND json_extract(metadata, '$.ai_unmapped_columns') IS NOT NULL
        LIMIT 1
        """,
        ("test_unmapped.csv",)
    ).fetchone()

assert result is not None, "Expected DB query to find unmapped columns record"
db_unmapped = json.loads(result[0])
print(f"    DB unmapped columns: {db_unmapped}")
assert "xrf_coeff_delta" in db_unmapped
print("    PASS: DB query returns unmapped columns correctly")

# ── Summary ───────────────────────────────────────────────
print("\n" + "=" * 55)
print("All checks passed — unmapped column warning working correctly")
print("=" * 55)
