from typing import Generator
import re
import struct

def parse(content_bytes: bytes) -> Generator[dict, None, None]:
    """
    Byte-safe universal fallback parser.
    Handles:
      1. Length-prefixed binary records with NUL-separated key=value fields
      2. Simple NUL-separated key=value streams
      3. Plain text with non-UTF8 tolerance
      4. Opaque binary via hex-dump chunking
    Yields records with fields extracted from the content.
    """
    if b'\x00' in content_bytes:
        # Try length-prefixed binary format first (e.g., synthetic .bin files)
        records = list(_parse_length_prefixed(content_bytes))
        if records:
            yield from records
            return

        # Try simple NUL-separated key=value extraction
        records = list(_parse_nul_kv(content_bytes))
        if records:
            yield from records
            return

        # Fallback: opaque binary hex-dump
        for i in range(0, len(content_bytes), 16):
            chunk = content_bytes[i:i+16]
            hex_str = ' '.join(f'{b:02x}' for b in chunk)
            yield {"raw_message": hex_str}
    else:
        # Text Branch: Force string decoding with replacement
        content_str = content_bytes.decode('utf-8', errors='backslashreplace')
        for line in content_str.splitlines():
            line = line.strip()
            if line:
                yield {"raw_message": line}


def _parse_length_prefixed(content_bytes: bytes) -> list[dict]:
    """
    Parse binary content with length-prefixed, NUL-delimited key=value records.

    Format:
      [magic header bytes]
      [4-byte LE uint32 length][NUL-separated key=value payload] ...

    The magic header is skipped by scanning for the first valid
    length-prefixed record.
    """
    kv_pattern = re.compile(r'^([a-zA-Z_][a-zA-Z0-9_]*)=(.+)$')
    records = []

    # Skip magic/header bytes: scan for the first plausible length prefix
    # by looking for a 4-byte LE uint32 that, when used as a record length,
    # leads to content containing key=value NUL-separated pairs.
    offset = _find_first_record_offset(content_bytes)
    if offset < 0:
        return []

    total = len(content_bytes)
    while offset + 4 <= total:
        # Read 4-byte little-endian record length
        rec_len = struct.unpack_from('<I', content_bytes, offset)[0]
        offset += 4

        # Sanity check: record length must be reasonable
        if rec_len == 0 or rec_len > 1_000_000 or offset + rec_len > total:
            break

        # Extract the record payload
        payload = content_bytes[offset:offset + rec_len]
        offset += rec_len

        # Split payload on NUL bytes and extract key=value pairs
        segments = payload.split(b'\x00')
        record: dict = {}
        for seg in segments:
            try:
                text = seg.decode('utf-8', errors='strict').strip()
            except UnicodeDecodeError:
                continue
            if not text:
                continue
            m = kv_pattern.match(text)
            if m:
                record[m.group(1)] = m.group(2)

        if record:
            records.append(_finalize_record(record))

    return records


def _find_first_record_offset(content_bytes: bytes) -> int:
    """
    Scan the first 64 bytes to find where length-prefixed records start.
    Validates by checking that at least TWO consecutive records have
    valid framing, to avoid false positives from misaligned offsets.
    Returns the byte offset of the first valid 4-byte length prefix,
    or -1 if no valid framing is found.
    """
    total = len(content_bytes)
    # Try offsets in the first 64 bytes (covers most magic headers)
    for start in range(0, min(64, total - 4)):
        rec_len = struct.unpack_from('<I', content_bytes, start)[0]
        # Check: length must be reasonable and the record must contain
        # at least one key=value pair with NUL separators.
        if rec_len < 10 or rec_len > 100_000:
            continue
        end = start + 4 + rec_len
        if end > total:
            continue
        payload = content_bytes[start + 4:end]
        if b'=' not in payload or b'\x00' not in payload:
            continue

        # Verify at least one valid KV pair in first record
        first_valid = False
        for seg in payload.split(b'\x00')[:3]:
            try:
                text = seg.decode('utf-8', errors='strict')
            except UnicodeDecodeError:
                continue
            if re.match(r'^[a-zA-Z_]\w*=.+$', text):
                first_valid = True
                break

        if not first_valid:
            continue

        # Validate the SECOND record too (prevents false positives)
        if end + 4 <= total:
            next_len = struct.unpack_from('<I', content_bytes, end)[0]
            if next_len < 10 or next_len > 100_000 or end + 4 + next_len > total:
                continue
            next_payload = content_bytes[end + 4:end + 4 + next_len]
            if b'=' not in next_payload or b'\x00' not in next_payload:
                continue
            # Check for valid KV in second record
            second_valid = False
            for seg in next_payload.split(b'\x00')[:3]:
                try:
                    text = seg.decode('utf-8', errors='strict')
                except UnicodeDecodeError:
                    continue
                if re.match(r'^[a-zA-Z_]\w*=.+$', text):
                    second_valid = True
                    break
            if not second_valid:
                continue

        return start
    return -1


def _parse_nul_kv(content_bytes: bytes) -> list[dict]:
    """
    Parse binary content with NUL-separated key=value fields.
    Records are separated by non-printable header bytes.
    """
    # Split on NUL bytes, decode each segment
    segments = content_bytes.split(b'\x00')
    kv_pattern = re.compile(r'^([a-zA-Z_][a-zA-Z0-9_]*)=(.+)$')

    records = []
    current_record: dict = {}

    for seg in segments:
        # Skip empty or pure binary header segments
        try:
            text = seg.decode('utf-8', errors='strict').strip()
        except UnicodeDecodeError:
            # Binary header — flush current record and skip
            if current_record:
                records.append(_finalize_record(current_record))
                current_record = {}
            continue

        if not text:
            continue

        m = kv_pattern.match(text)
        if m:
            key, value = m.group(1), m.group(2)
            if key == 'timestamp' and current_record.get('timestamp'):
                # New record starts with a new timestamp
                records.append(_finalize_record(current_record))
                current_record = {}
            current_record[key] = value
        else:
            # Non-KV text found after binary header — flush and start new
            if current_record:
                records.append(_finalize_record(current_record))
                current_record = {}

    # Flush last record
    if current_record:
        records.append(_finalize_record(current_record))

    return records


def _finalize_record(record: dict) -> dict:
    """Ensure the record has a raw_message field."""
    if 'raw_message' not in record:
        # Build raw_message from event_name or all fields
        if 'event_name' in record:
            record['raw_message'] = record['event_name']
        else:
            record['raw_message'] = ' | '.join(f'{k}={v}' for k, v in record.items())
    return record
